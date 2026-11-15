"""Independent opportunity labels using the inherited execution economics."""
from common import *
from collections import Counter

class Tape:
    def __init__(self,contract,start,end):
        self.raw=load_minutes(contract,start-M,end);self.mark=load_mark(contract,start-M,end);self.fund=load_funding(contract,start-2*D,end)
        self.times=self.raw.ts.to_numpy('int64');self.a=self.raw[['open','high','low','close','volume','quote_volume']].to_numpy(float)
        self.mt=self.mark.ts.to_numpy('int64');self.ma=self.mark[['open','high','low','close']].to_numpy(float)
        self.funding={};self.bounds={}
        for row in self.fund.itertuples(index=False):
            self.funding.setdefault(int(row.ts)//M*M,[]).append((int(row.ts),float(row.last_funding_rate)))
        for month,g in self.fund.groupby(pd.to_datetime(self.fund.ts,unit='ms',utc=True).dt.strftime('%Y-%m')):
            self.bounds[month]=g[['ts','funding_interval_hours']].to_numpy(float)
    def bar(self,t,mark=False):
        times,a=(self.mt,self.ma) if mark else (self.times,self.a)
        i=np.searchsorted(times,t)
        if i==len(times) or times[i]!=t or not np.isfinite(a[i,:4]).all():return None
        return a[i]
    def funding_ok(self,t):
        rows=self.bounds.get(pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m'))
        if rows is None or len(rows)==0:return False
        pos=np.searchsorted(rows[:,0],t,side='right');before=rows[max(0,pos-1)];after=rows[min(len(rows)-1,pos)]
        allowance=max(before[1],after[1])*3600000*1.5
        if pos==0:return rows[0,0]-t<=allowance
        if pos==len(rows):return t-rows[-1,0]<=allowance
        return after[0]-before[0]<=allowance

def label_one(s,tape,guard,end):
    side=int(s.side);t=int(s.ts);fee=slip=.0005
    base={'observation_id':s.observation_id,'variant':s.variant,'decision_ts':int(s.decision_ts),'label_status':'','entry_ts':t}
    def reject(reason):return dict(base,label_status=reason)
    if t>=end:return reject('outside_label_segment')
    if (t//M+480)%1440>=1320:return reject('not_executed_late_day')
    if t>=load_quarantine().get(s.symbol,{}).get('known_ts',10**18):return reject('not_executed_quarantine')
    if not guard.eligible(s.symbol,side,t):return reject('not_executed_pool_changed')
    prev=tape.bar(t-M);prem=tape.bar(t-M,True)
    if prev is None or prem is None or prev[4]<=0:return reject('not_executed_prior_data')
    b=tape.bar(t);mark=tape.bar(t,True)
    if b is None or mark is None:return reject('missing_entry_execution')
    raw=float(b[0]);entry=raw*(1+side*slip);stop=float(s.stop_price);distance=side*(entry-stop)
    if side*(entry-s.signal_close)>.25*s.atr:return reject('not_executed_entry_deviation')
    if distance<=0 or distance>1.5*s.atr or 2*distance/entry<.006:return reject('not_executed_stop_cost')
    if .001*prev[5]<10:return reject('not_executed_liquidity_minimum')
    target=entry+side*2*distance
    if min(target,stop)<=0:return reject('not_executed_invalid_levels')
    qty=1/entry;funding=0.;entryslip=qty*abs(entry-raw)
    for j in range(61):
        now=t+j*M
        if now>=end:return reject('label_crosses_boundary')
        b=tape.bar(now);mark=tape.bar(now,True)
        if b is None or mark is None:return reject('missing_held_price')
        if not tape.funding_ok(now):return reject('missing_held_funding')
        why=None;exitraw=None;exit_ts=None
        if j>0:
            gapstop=b[0]<=stop if side==1 else b[0]>=stop
            gaptarget=b[0]>=target if side==1 else b[0]<=target
            why='gap_stop' if gapstop else 'gap_target' if gaptarget else 'day_close' if (now//M+480)%1440>=1435 else 'time60' if j>=60 else None
        if why:
            for ft,rate in tape.funding.get(now,[]):funding+=max(0.,side*qty*mark[0]*rate)
            exitraw=float(b[0]);exit_ts=now
        else:
            sh=b[2]<=stop if side==1 else b[1]>=stop;th=b[1]>=target if side==1 else b[2]<=target
            for ft,rate in tape.funding.get(now,[]):
                charge=side*qty*mark[0]*rate
                funding+=max(0.,charge) if j==0 or sh or th else charge
            if sh or th:why='stop' if sh else 'target';exitraw=stop if sh else target;exit_ts=now+M
        if why:
            fill=exitraw*(1-side*slip);gross=side*qty*(exitraw-raw);fees=fee+qty*fill*fee;slippage=entryslip+qty*abs(fill-exitraw);net=gross-fees-slippage-funding
            return dict(base,label_status='valid',exit_ts=int(exit_ts),entry=entry,stop=stop,target=target,reason=why,
              gross_per_notional=float(gross),fees_per_notional=float(fees),slippage_per_notional=float(slippage),funding_per_notional=float(funding),
              net_per_notional=float(net),net_R=float(net/(distance/entry)),y=int(net>0))
    raise AssertionError('No exit within61 bars')

def make_labels(which):
    signals=pd.read_parquet(OUT/'signals/all.parquet');guard=RankTrendGuard();out=[]
    if which=='development':signals=signals[signals.decision_ts.lt(CAL_END)].copy()
    else:
        assert (OUT/'models/FROZEN.json').exists(),'Do not read evaluation labels before model freeze'
        signals=signals[signals.decision_ts.ge(CAL_END)].copy()
    for contract,group in signals.groupby('contract'):
        start=int(group.ts.min());end=CAL_END if which=='development' else END
        tape=Tape(contract,start,end)
        for s in group.itertuples(index=False):
            boundary=TRAIN_END if s.decision_ts<TRAIN_END else CAL_END if s.decision_ts<CAL_END else END
            if which=='development' and s.decision_ts+65*M>=boundary:
                out.append({'observation_id':s.observation_id,'variant':s.variant,'decision_ts':s.decision_ts,'label_status':'purged_65min'});continue
            out.append(label_one(s,tape,guard,boundary))
        print('LABEL',which,contract,len(group),flush=True)
    result=pd.DataFrame(out);assert result.observation_id.is_unique
    save('labels/'+which+'.parquet',result)
    counts=result.groupby(['variant','label_status']).size()
    dump(OUT/'labels'/f'{which}-audit.json',{'counts':{str(k):int(v) for k,v in counts.items()},'future_labels_used_to_filter_account':False})
    return result

if __name__=='__main__':make_labels(sys.argv[1])

