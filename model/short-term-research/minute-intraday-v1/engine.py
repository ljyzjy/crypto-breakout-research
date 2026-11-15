"""Single minute strategy; event ordering and costs explicit, no order API."""
from dataclasses import dataclass,asdict
from collections import Counter
import math
import numpy as np
import pandas as pd
from prepare_data import ROOT,read,dump,sha

MINUTE=60_000
PRICE_COLS=['open','high','low','close','volume','quote_volume']

class Market:
    def __init__(self):
        self.manifest=read(ROOT/'data-manifest.json')
        self.entries={(r['contract'],r['month'],r['kind']):r for r in self.manifest['records']}
        self.month=None;self.px={};self.mark={};self.funding={};self.bounds={}
    def change_month(self,ts):
        month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
        if month==self.month:return
        self.month=month;self.px={};self.mark={};self.funding={};self.bounds={}
        start=pd.Timestamp(month+'-01',tz='UTC');end=start+pd.offsets.MonthBegin(1)
        self.base=int(start.timestamp()*1000);self.count=int((end-start).total_seconds()/60)
        ix=pd.date_range(start,end,freq='min',inclusive='left')
        for (c,m,k),r in self.entries.items():
            if m!=month:continue
            d=pd.read_parquet(ROOT/r['path'])
            if k=='fundingRate':
                events={}
                for row in d.itertuples(index=False):
                    events.setdefault(int(row.ts)//MINUTE*MINUTE,[]).append((int(row.ts),float(row.last_funding_rate)))
                self.funding[c]=events
                self.bounds[c]=d[['ts','funding_interval_hours']].to_numpy(float)
            else:
                d.index=pd.to_datetime(d.ts,unit='ms',utc=True)
                cols=PRICE_COLS if k=='klines' else PRICE_COLS[:4]
                a=d.reindex(ix)[cols].to_numpy(float)
                (self.px if k=='klines' else self.mark)[c]=a
    def bar(self,c,ts,mark=False):
        data=(self.mark if mark else self.px).get(c)
        i=(ts-self.base)//MINUTE
        if data is None or i<0 or i>=self.count:return None
        x=data[i]
        return x if np.isfinite(x[:4]).all() else None
    def funding_ok(self,c,ts):
        if c not in self.funding:return False
        rows=self.bounds[c]
        if len(rows)<1:return False
        pos=np.searchsorted(rows[:,0],ts,side='right')
        # Ex-post coverage audit, never used to choose an entry or rank a coin.
        before=rows[max(0,pos-1)];after=rows[min(len(rows)-1,pos)]
        allowance=max(before[1],after[1])*3_600_000*1.5
        if pos==0:return rows[0,0]-ts<=allowance
        if pos==len(rows):return ts-rows[-1,0]<=allowance
        return after[0]-before[0]<=allowance

@dataclass
class Position:
    symbol:str;contract:str;side:int;qty:float;entry_ts:int;signal_ts:int
    raw_entry:float;entry:float;margin:float;stop:float;target:float
    entry_fee:float;entry_slip:float;funding:float=0.;last_mark:float=0.
    score:float=0.;rank:int=0;planned_risk:float=0.

def metrics(curve,trades,initial=1000.):
    if curve.empty:return {}
    last=float(curve.equity.iloc[-1]);days=(curve.ts.iloc[-1]-curve.ts.iloc[0]+MINUTE)/86_400_000
    ret=100*(last/initial-1);peak=np.maximum.accumulate(np.r_[initial,curve.equity.to_numpy()])[1:]
    dd=100*(1-curve.equity.to_numpy()/peak)
    t=pd.DataFrame(trades)
    return {'initial':initial,'final_equity':last,'return_pct':ret,
        'annualized_return_pct':100*((last/initial)**(365/days)-1) if days>=365 and last>0 else None,
        'elapsed_days':float(days),'max_drawdown':float(dd.max()),'trades':len(t),
        'win_rate':float(100*t.net.gt(0).mean()) if len(t) else 0.,
        'gross_pnl':float(t.gross.sum()) if len(t) else 0.,'fees':float(t.fees.sum()) if len(t) else 0.,
        'slippage_cost':float(t.slippage.sum()) if len(t) else 0.,'funding_cost':float(t.funding.sum()) if len(t) else 0.,
        'net_pnl':last-initial,'average_trade_net':float(t.net.mean()) if len(t) else 0.,
        'mean_holding_minutes':float(t.holding_minutes.mean()) if len(t) else 0.,
        'mean_exposure_pct':float(curve.exposure.mean()),
        'profit_factor':float(t.loc[t.net>0,'net'].sum()/-t.loc[t.net<0,'net'].sum()) if len(t) and t.net.lt(0).any() else None,
        'ledger_error':float(last-initial-t.net.sum()) if len(t) else float(last-initial)}

def simulate(scenario,signals=None,start=None,end=None,market=None,save=True):
    spec=read(ROOT/'protocol.json');start=start or spec['start'];end=end or spec['end']
    lo=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    hi=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    fee=scenario['fee'];slip=scenario['slippage'];delay=scenario['delay_minutes']
    candidates=pd.read_parquet(ROOT/'signals.parquet') if signals is None else signals.copy()
    candidates['exec_ts']=candidates.ts+delay*MINUTE
    candidates=candidates[candidates.exec_ts.ge(lo)&candidates.exec_ts.lt(hi)].copy()
    candidates['strength']=candidates.score.abs()
    candidates=candidates.sort_values(['exec_ts','strength','symbol'],ascending=[True,False,True])
    events={int(ts):list(g.to_dict('records')) for ts,g in candidates.groupby('exec_ts',sort=False)}
    market=market or Market();cash=1000.;positions={};trades=[];audits=[];issues=[]
    cooldown={};blocked_until=lo;peak=1000.;known_equity=1000.;day_start=1000.;current_day=None
    daily_paused=False;permanent_pause=False;pause_ts=None;daily_entries=0;reason_counts=Counter()
    rows=[];worst_stress=0.;total_minutes=(hi-lo)//MINUTE
    quarantine=read(ROOT/'quarantine.json') if (ROOT/'quarantine.json').exists() else {}

    def close(p,raw,ts,reason,ambiguous=False):
        nonlocal cash,blocked_until
        fill=raw*(1-p.side*slip)
        exitfee=p.qty*fill*fee;exit_slip=p.qty*abs(fill-raw)
        pnl=p.side*p.qty*(fill-p.entry)
        cash+=p.margin+pnl-exitfee
        gross=p.side*p.qty*(raw-p.raw_entry)
        net=gross-p.entry_slip-exit_slip-p.entry_fee-exitfee-p.funding
        trades.append({'symbol':p.symbol,'contract':p.contract,'side':'long' if p.side==1 else 'short',
          'signal_ts':p.signal_ts,'entry_ts':p.entry_ts,'exit_ts':int(ts),'entry':p.entry,'exit':fill,'qty':p.qty,
          'reason':reason,'ambiguous':ambiguous,'gross':gross,'fees':p.entry_fee+exitfee,
          'slippage':p.entry_slip+exit_slip,'funding':p.funding,'net':net,
          'holding_minutes':(ts-p.entry_ts)/MINUTE,'rank':p.rank,'score':p.score,'planned_risk':p.planned_risk})
        cooldown[p.symbol]=int(ts)+60*MINUTE
        blocked_until=max(blocked_until,int(ts//MINUTE*MINUTE)+MINUTE)
        del positions[p.symbol]

    try:
        for n,ts in enumerate(range(lo,hi,MINUTE)):
            market.change_month(ts)
            beijing=(ts//MINUTE+480);day=beijing//1440;minute=beijing%1440
            if day!=current_day:
                current_day=day;day_start=known_equity;daily_paused=False;daily_entries=0
            if known_equity<=day_start*.985:daily_paused=True
            dd_known=1-known_equity/peak
            if dd_known>=.08 and not permanent_pause:permanent_pause=True;pause_ts=ts
            # Scheduled exits at this minute open use previously available information.
            for p in list(positions.values()):
                b=market.bar(p.contract,ts);m=market.bar(p.contract,ts,True)
                if b is None or m is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                stop_hit=(b[0]<=p.stop if p.side==1 else b[0]>=p.stop)
                target_hit=(b[0]>=p.target if p.side==1 else b[0]<=p.target)
                why=('gap_stop' if stop_hit else 'gap_target' if target_hit else
                     'account_pause' if permanent_pause else 'daily_pause' if daily_paused else
                     'day_close' if minute>=1435 else 'time60' if ts-p.entry_ts>=60*MINUTE else None)
                if why:
                    # Settlement at an open boundary is ambiguous: debit only, no income credit.
                    for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                        charge=max(0.,p.side*p.qty*m[0]*rate);cash-=charge;p.funding+=charge
                    close(p,float(b[0]),ts,why)
            if ts in events:
                for r in events[ts]:
                    s=r['symbol'];c=r['contract'];side=int(r['side'])
                    rejected=None
                    if permanent_pause:rejected='account_pause'
                    elif daily_paused:rejected='daily_pause'
                    elif minute>=1320:rejected='late_day'
                    elif ts<blocked_until:rejected='exit_wait'
                    elif len(positions)>=2:rejected='slots_full'
                    elif daily_entries>=6:rejected='day_trade_cap'
                    elif s in positions:rejected='already_held'
                    elif ts<cooldown.get(s,0):rejected='symbol_cooldown'
                    elif ts>=quarantine.get(s,{}).get('known_ts',10**18):rejected='known_quarantine'
                    if rejected:reason_counts[rejected]+=1;continue
                    # Recheck current known minute after an added execution delay.
                    prev=market.bar(c,ts-MINUTE);prem=market.bar(c,ts-MINUTE,True)
                    if prev is None or prem is None or prev[4]<=0:reason_counts['prior_data_unusable']+=1;continue
                    b=market.bar(c,ts);m=market.bar(c,ts,True)
                    if b is None or m is None:raise ValueError(f'entry_execution_missing:{s}:{ts}')
                    price=float(b[0])*(1+side*slip);distance=1.5*float(r['atr']);stopfrac=distance/price
                    risk_fraction=.00125 if dd_known>=.05 else .0025
                    equity=cash+sum(p.margin+p.side*p.qty*(p.last_mark-p.entry) for p in positions.values())
                    existing_risk=sum(p.qty*(max(0.,p.side*(p.last_mark-p.stop))+p.stop*(fee+slip)) for p in positions.values())
                    allowance=max(0.,min(equity*risk_fraction,equity*.005-existing_risk))
                    gross_existing=sum(p.qty*p.last_mark for p in positions.values())
                    amount=min(allowance/(stopfrac+2*fee+2*slip),.5*equity,
                               max(0.,equity-gross_existing),cash/(1+fee),.001*float(prev[5]))
                    if amount<10:reason_counts['risk_or_liquidity_budget']+=1;continue
                    qty=amount/price;entryfee=amount*fee
                    stop=price-side*distance;target=price+side*2*distance
                    if min(stop,target)<=0:reason_counts['invalid_levels']+=1;continue
                    planned=amount*(stopfrac+2*fee+2*slip)
                    p=Position(s,c,side,qty,ts,int(r['ts']),float(b[0]),price,amount,stop,target,
                               entryfee,qty*abs(price-float(b[0])),last_mark=float(prem[3]),score=float(r['score']),rank=int(r['rank']),planned_risk=planned)
                    positions[s]=p;cash-=amount+entryfee;daily_entries+=1
                    audits.append({'ts':ts,'signal_ts':int(r['ts']),'symbol':s,'side':side,'rank':int(r['rank']),
                       'score':float(r['score']),'known_equity':equity,'notional':amount,'risk_fraction':risk_fraction,
                       'planned_loss':planned,'aggregate_planned_loss':existing_risk+planned,'gross_after':gross_existing+amount,
                       'previous_quote_volume':float(prev[5]),'slots':len(positions),'day_entries':daily_entries})
            # Audit funding coverage, then settle and process conservative intraminute exits.
            stress_equity=cash
            for p in positions.values():
                m=market.bar(p.contract,ts,True)
                if m is None:raise ValueError(f'held_missing_mark:{p.symbol}:{ts}')
                adverse=m[2] if p.side==1 else m[1]
                stress_equity+=p.margin+p.side*p.qty*(adverse-p.entry)
            worst_stress=max(worst_stress,100*(1-stress_equity/peak))
            for p in list(positions.values()):
                b=market.bar(p.contract,ts);m=market.bar(p.contract,ts,True)
                if b is None or m is None:raise ValueError(f'held_missing_bar:{p.symbol}:{ts}')
                if not market.funding_ok(p.contract,ts):raise ValueError(f'held_funding_coverage_missing:{p.symbol}:{ts}')
                sh=b[2]<=p.stop if p.side==1 else b[1]>=p.stop
                th=b[1]>=p.target if p.side==1 else b[2]<=p.target
                for ft,rate in market.funding.get(p.contract,{}).get(ts,[]):
                    charge=p.side*p.qty*m[0]*rate
                    if p.entry_ts==ts or sh or th:charge=max(0.,charge)
                    cash-=charge;p.funding+=charge
                if sh or th:
                    close(p,p.stop if sh else p.target,ts+MINUTE,'stop' if sh else 'target',bool(sh and th))
                else:p.last_mark=float(m[3])
            if ts==hi-MINUTE:
                for p in list(positions.values()):close(p,float(market.bar(p.contract,ts)[3]),ts+MINUTE,'period_end')
            known_equity=cash+sum(p.margin+p.side*p.qty*(p.last_mark-p.entry) for p in positions.values())
            peak=max(peak,known_equity)
            exposure=100*sum(p.qty*p.last_mark for p in positions.values())/known_equity if known_equity>0 else 0.
            rows.append((ts+MINUTE,known_equity,100*(1-known_equity/peak),exposure,len(positions)))
            if cash<-.000001:raise ValueError(f'negative_cash:{ts}')
            if n and n%150000==0:print('SIM',scenario['id'],n,'/',total_minutes,flush=True)
    except ValueError as exc:
        issues.append(str(exc))
    curve=pd.DataFrame(rows,columns=['ts','equity','drawdown','exposure','positions'])
    summary=metrics(curve,trades)
    summary.update(scenario=scenario['id'],start=start,end=end,fee=fee,slippage=slip,delay_minutes=delay,
        valid_for_comparison=not issues,issues=issues,intrabar_stress_dd=worst_stress,
        permanent_pause_ts=pause_ts,rejection_counts=dict(reason_counts),signal_candidates=len(candidates),
        leverage_cap=1,seconds_execution_verified=False)
    if save:
        out=ROOT/'results';out.mkdir(exist_ok=True)
        curve.to_parquet(out/(scenario['id']+'-curve.parquet'),index=False)
        dump(out/(scenario['id']+'-trades.json'),trades)
        dump(out/(scenario['id']+'-entries.json'),audits)
        dump(out/(scenario['id']+'-summary.json'),summary)
    return summary,curve,trades,audits

if __name__=='__main__':
    spec=read(ROOT/'protocol.json');result=[]
    for scenario in spec['scenarios']:
        summary,*_=simulate(scenario);result.append(summary)
        print('COMPLETE',scenario['id'],summary.get('return_pct'),summary.get('max_drawdown'),summary['valid_for_comparison'],flush=True)
    dump(ROOT/'metrics.json',result)
