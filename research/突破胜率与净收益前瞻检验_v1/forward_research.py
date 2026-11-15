"""Run frozen 2026-May–Oct public-data experiment. No account/order access."""
from __future__ import annotations
import hashlib,importlib.util,json,math,sys
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_forward_2026'
NORM=WORK/'normalized'
GE=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge')
P3=GE/'outputs'/'feature-research-phase3'/'account'
PREV=HERE.parent/'突破柱融合研究_v1'
sys.path.insert(0,str(P3))
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
prior=load_module('prior_breakout_calculation',PREV/'research.py')
eng=load_module('target_engine',HERE/'engine_target_copy.py')
plan=json.loads((HERE/'冻结研究方案.json').read_text(encoding='utf-8'))
repair=json.loads((HERE/'标记价格日档补齐记录.json').read_text(encoding='utf-8'))
if not repair['complete']:raise RuntimeError('Incomplete daily mark repair')
M=60_000;H=60*M;Q=15*M
WARM=int(pd.Timestamp('2026-04-01',tz='UTC').timestamp()*1000)
START=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
END=int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000)
GRID=np.arange(WARM,END,M,dtype=np.int64)
assert len(GRID)%60==0

def dump(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False,
        default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')

def dense(path,columns):
    if not path.is_file():return np.full((len(GRID),len(columns)),np.nan)
    d=pd.read_parquet(path)
    if d.ts.duplicated().any():raise ValueError('Duplicate input minute')
    return d.set_index('ts').reindex(GRID)[columns].to_numpy(float)

def valid_trade(a):
    o,h,l,c,v,q=a[:,:6].T
    ok=np.isfinite(a[:,:6]).all(axis=1)&(a[:,:6]>0).all(axis=1)
    ok&=(h>=np.maximum.reduce([o,l,c]))&(l<=np.minimum.reduce([o,h,c]))
    return ok

class FixedMarket:
    def __init__(self):
        self.trade={};self.mark={};self.funding={};self.bounds={};self.minute_quality={}
        for item in plan['fixed_pool']:
            c=item['contract']
            a=dense(NORM/f'{c}_klines.parquet',['open','high','low','close','volume','quote_volume','trade_count'])
            m=dense(NORM/f'{c}_markPriceKlines.parquet',['open','high','low','close'])
            # Treat malformed available OHLC as data errors rather than substitute prices.
            for name,x in [('trade',a),('mark',m)]:
                finite=np.isfinite(x[:,:4]).all(axis=1)
                y=x[finite,:4]
                if len(y) and ((y<=0).any() or (y[:,1]<np.max(y[:,[0,2,3]],axis=1)).any() or (y[:,2]>np.min(y[:,[0,1,3]],axis=1)).any()):
                    raise ValueError('Malformed '+name+' OHLC: '+c)
            self.trade[c]=a;self.mark[c]=m
            self.minute_quality[c]={'trade_missing':int((~np.isfinite(a[:,:4]).all(axis=1)).sum()),
                                    'mark_missing_in_test':int((~np.isfinite(m[GRID>=START,:4]).all(axis=1)).sum())}
            fpath=NORM/f'{c}_fundingRate.parquet';fund={};bounds={}
            if fpath.exists():
                f=pd.read_parquet(fpath)
                if f.ts.duplicated().any() or not np.isfinite(f[['funding_interval_hours','last_funding_rate']]).all().all() or (f.funding_interval_hours<=0).any():
                    raise ValueError('Invalid funding records: '+c)
                for row in f.itertuples(index=False):
                    ft=int(row.ts);fund.setdefault(ft//M*M,[]).append((ft,float(row.last_funding_rate)))
                months=pd.to_datetime(f.ts,unit='ms',utc=True).dt.strftime('%Y-%m')
                for month,g in f.groupby(months):bounds[month]=g[['ts','funding_interval_hours']].sort_values('ts').to_numpy(float)
            self.funding[c]=fund;self.bounds[c]=bounds
            print('MARKET_LOADED',c,flush=True)
    def change_month(self,ts):pass
    def bar(self,c,ts,mark=False):
        i=(int(ts)-WARM)//M
        if i<0 or i>=len(GRID) or GRID[i]!=ts:return None
        a=(self.mark if mark else self.trade).get(c)
        if a is None or not np.isfinite(a[i,:4]).all():return None
        return a[i]
    def funding_ok(self,c,ts):
        month=pd.Timestamp(ts,unit='ms',tz='UTC').strftime('%Y-%m')
        rows=self.bounds.get(c,{}).get(month)
        if rows is None or not len(rows):return False
        pos=np.searchsorted(rows[:,0],ts,side='right')
        before=rows[max(0,pos-1)];after=rows[min(len(rows)-1,pos)]
        allowance=max(before[1],after[1])*3_600_000*1.5
        if pos==0:return rows[0,0]-ts<=allowance
        if pos==len(rows):return ts-rows[-1,0]<=allowance
        return after[0]-before[0]<=allowance

class FixedGuard:
    def __init__(self,market):
        self.market=market;self.mapping={x['symbol']:x['contract'] for x in plan['fixed_pool']}
        self.liq={x['symbol']:x['liquidity_rank'] for x in plan['fixed_pool']}
        self.hours={};self.trend={};self.ranks={};self.correlation_cache={}
        count=len(GRID)//60
        for s,c in self.mapping.items():
            a=market.trade[c];ok=valid_trade(a)
            h=a.reshape(count,60,7);valid=ok.reshape(count,60).all(axis=1)
            close=pd.Series(np.where(valid,h[:,-1,3],np.nan))
            qv=pd.Series(np.where(valid,h[:,:,5].sum(axis=1),np.nan))
            returns=np.log(close).diff();r6=returns.rolling(6,min_periods=6).sum()
            vol=returns.rolling(24,min_periods=24).std(ddof=1)
            lags=pd.concat([qv.shift(24*i) for i in range(1,21)],axis=1)
            med=lags.median(axis=1).where(lags.notna().all(axis=1))
            score=(r6/vol.where(vol>0)).to_numpy();rvol=(qv/med.where(med>0)).to_numpy()
            self.hours[s]={'returns':returns.to_numpy(),'score':score,'rvol':rvol}
            q=a.reshape(len(GRID)//15,15,7);qok=ok.reshape(-1,15).all(axis=1)
            qclose=pd.Series(np.where(qok,q[:,-1,3],np.nan))
            ema=qclose.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
            direction=np.select([qclose.gt(ema)&ema.gt(ema.shift()),qclose.lt(ema)&ema.lt(ema.shift())],[1,-1],0)
            self.trend[s]=direction
        for hidx in range(count):
            hour=WARM+(hidx+1)*H
            for side in [-1,1]:
                candidates=[]
                for s,c in self.mapping.items():
                    z=self.hours[s];score=z['score'][hidx];rv=z['rvol'][hidx]
                    if np.isfinite(score) and np.isfinite(rv) and rv>=1.5 and score*side>0:
                        candidates.append((s,c,float(score),float(rv)))
                candidates.sort(key=lambda r:(-abs(r[2]),self.liq[r[0]],r[0]))
                for rank,(s,c,score,rv) in enumerate(candidates[:3],1):
                    self.ranks[(hour,s,side)]={'hour':hour,'symbol':s,'contract':c,'side':side,
                        'score':score,'rvol':rv,'rank':rank,'liquidity_rank':self.liq[s]}
    def eligible(self,s,side,ts):
        hour=ts//H*H
        if (hour,s,side) not in self.ranks or s not in self.trend:return False
        qi=(ts-WARM)//Q-1
        return 0<=qi<len(self.trend[s]) and self.trend[s][qi]==side
    def rank(self,s,side,ts):return self.ranks[(ts//H*H,s,side)]
    def correlation(self,a,sa,b,sb,ts):
        hour=ts//H*H;key=(hour,a,b)
        if key not in self.correlation_cache:
            idx=(hour-WARM)//H-1
            if a not in self.hours or b not in self.hours or idx<71:
                rho=None
            else:
                x=self.hours[a]['returns'][idx-71:idx+1];y=self.hours[b]['returns'][idx-71:idx+1]
                rho=float(np.corrcoef(x,y)[0,1]) if np.isfinite(x).all() and np.isfinite(y).all() and np.std(x)>0 and np.std(y)>0 else None
            self.correlation_cache[key]=rho
        rho=self.correlation_cache[key]
        return None if rho is None else sa*sb*rho

def validate_warm_features(guard):
    """Compare calculations against the previous frozen hourly feature data."""
    checks=0;skips=0;maximum=0.;regime_checks=0;regime_mismatch=0
    times=[int(pd.Timestamp(f'2026-04-{day} {hour}:00',tz='UTC').timestamp()*1000)
           for day in (25,26) for hour in ('04','12','20')]
    old_regime=pd.read_parquet(P3/'regimes.parquet')
    for s in guard.mapping:
        old=pd.read_parquet(GE/'outputs'/'feature-research-phase2'/'feature_outputs'/'hourly'/f'{s}.parquet')
        old=old.set_index('ts')
        reg=old_regime[old_regime.symbol.eq(s)].set_index('ts')
        for ts in times:
            idx=(ts-WARM)//H-1
            if ts not in old.index or idx<0:skips+=1;continue
            r=old.loc[ts]
            expected=[float(r.r6/r.vol24) if pd.notna(r.r6) and pd.notna(r.vol24) and r.vol24>0 else np.nan,float(r.quote_rvol)]
            got=[guard.hours[s]['score'][idx],guard.hours[s]['rvol'][idx]]
            for a,b in zip(expected,got):
                if np.isfinite(a) and np.isfinite(b):
                    error=abs(a-b)/max(1.,abs(a));maximum=max(maximum,error);checks+=1
                elif np.isfinite(a)!=np.isfinite(b):
                    raise ValueError('Warmup feature availability mismatch: '+s)
                else:skips+=1
            qi=(ts-WARM)//Q-1
            if ts in reg.index and qi>=0:
                regime_checks+=1;regime_mismatch+=int(int(reg.loc[ts,'direction'])!=int(guard.trend[s][qi]))
    result={'paired_hourly_values':checks,'maximum_relative_error':maximum,'skipped_missing_values':skips,
            'quarter_direction_checks':regime_checks,'quarter_direction_mismatches':regime_mismatch}
    dump(HERE/'预热特征对照.json',result)
    if checks<50 or maximum>1e-7 or regime_mismatch:raise ValueError('Warmup feature validation failed')
    print('WARMUP_FEATURES_VALIDATED',json.dumps(result),flush=True)

def ref_state(refs,i,side):
    for s in ['BTCUSDT','ETHUSDT']:
        x=refs[s];ratio=x['ratio'][i]
        if not np.isfinite(ratio) or ratio<1.5 or not x['valid'][i]:return False
        if not (x['close'][i]>x['upper'][i] if side==1 else x['close'][i]<x['lower'][i]):return False
    return True

def signal_record(symbol,contract,side,t0,decision,close,atr,stop,level,rank,variant):
    return {'ts':decision+M,'decision_ts':decision,'feature_known_ts':decision,
       'observation_id':f'{variant}|{symbol}|{t0}|{side}','symbol':symbol,'contract':contract,'side':side,
       'signal_close':float(close),'atr':float(atr),'stop_price':float(stop),'level':float(level),
       'break_ts':t0,'touch_ts':t0,'quarter_start':t0//Q*Q,'hour':rank['hour'],
       'score':rank['score'],'rank':rank['rank'],'rvol':rank['rvol'],
       'liquidity_rank':rank['liquidity_rank'],'risk_multiplier':1.}

def create_signals(market,guard):
    prior.smoke_checks()
    refs={}
    for s in ['BTCUSDT','ETHUSDT']:
        a=market.trade[guard.mapping[s]];ok=valid_trade(a);f=prior.calculate(a,ok)
        refs[s]={'close':a[:,3],'valid':ok,**f}
    first_signals=[];confirmed=[];counts=Counter()
    for symbol,contract in guard.mapping.items():
        a=market.trade[contract];valid=valid_trade(a);f=prior.calculate(a,valid)
        long=valid&f['current_prefix_valid']&(a[:,3]>f['upper'])
        short=valid&f['current_prefix_valid']&(a[:,3]<f['lower'])
        cross=np.flatnonzero(long|short)
        if not len(cross):continue
        first=cross[np.r_[True,np.diff(cross//15)!=0]];last=-10**18
        for i in first:
            t0=int(GRID[i]);decision=t0+M;entry=decision+M
            if decision>=END:break
            if t0-last<60*M:counts['event_cooldown']+=1;continue
            last=t0
            if decision<START:continue
            counts['first_events']+=1
            quarter_end=(t0//Q+1)*Q
            if entry>=quarter_end:counts['outside_quarter']+=1;continue
            side=1 if long[i] else -1
            if not guard.eligible(symbol,side,decision):counts['rank_trend']+=1;continue
            if not ref_state(refs,i,side):counts['reference_filter']+=1;continue
            atr=float(f['atr'][i]);close=float(a[i,3]);level=float(f['upper'][i] if side==1 else f['lower'][i])
            if not np.isfinite(atr) or atr<=0:counts['atr_unknown']+=1;continue
            stop=float(a[i,2]-.1*atr if side==1 else a[i,1]+.1*atr);distance=side*(close-stop)
            if distance<=0 or distance>1.5*atr or 2*distance/close<.006:counts['stop_cost']+=1;continue
            rank=guard.rank(symbol,side,decision)
            first_signals.append(signal_record(symbol,contract,side,t0,decision,close,atr,stop,level,rank,'first'))
            # Confirmation only uses the next fully closed minute and updates
            # both reference instruments at that same information timestamp.
            j=i+1;d2=decision+M;e2=d2+M
            if e2>=quarter_end or j>=len(GRID) or GRID[j]!=t0+M or not valid[j] or not f['current_prefix_valid'][j]:
                counts['confirmation_too_late_or_invalid']+=1;continue
            if not guard.eligible(symbol,side,d2) or not ref_state(refs,j,side):
                counts['confirmation_guard']+=1;continue
            close2=float(a[j,3])
            if side*(close2-level)<=0:counts['confirmation_back_inside']+=1;continue
            stop2=float(min(a[i,2],a[j,2])-.1*atr if side==1 else max(a[i,1],a[j,1])+.1*atr)
            distance2=side*(close2-stop2)
            if distance2<=0 or distance2>1.5*atr or 2*distance2/close2<.006:
                counts['confirmation_stop_cost']+=1;continue
            rank2=guard.rank(symbol,side,d2)
            confirmed.append(signal_record(symbol,contract,side,t0,d2,close2,atr,stop2,level,rank2,'confirm'))
        print('SIGNALS_BUILT',symbol,'first',len(first_signals),'confirmed',len(confirmed),flush=True)
    cols=['ts','decision_ts','feature_known_ts','observation_id','symbol','contract','side','signal_close','atr','stop_price','level','break_ts','touch_ts','quarter_start','hour','score','rank','rvol','liquidity_rank','risk_multiplier']
    first=pd.DataFrame(first_signals,columns=cols).sort_values(['ts','symbol']).reset_index(drop=True)
    confirm=pd.DataFrame(confirmed,columns=cols).sort_values(['ts','symbol']).reset_index(drop=True)
    for x in [first,confirm]:
        if len(x):
            assert (x.ts==x.decision_ts+M).all() and (x.ts<x.quarter_start+Q).all()
            assert (x.feature_known_ts<=x.decision_ts).all() and x.observation_id.is_unique
    first.to_parquet(HERE/'first_signals.parquet',index=False)
    confirm.to_parquet(HERE/'confirmed_signals.parquet',index=False)
    counts['first_eligible']=len(first);counts['confirmed_eligible']=len(confirm)
    dump(HERE/'信号生成核对.json',{'counts':dict(counts),'data_quality':market.minute_quality,
        'scope':'All features known no later than the decision; minute OHLC and nominal fills only.',
        'plan_sha256':hashlib.sha256((HERE/'冻结研究方案.json').read_bytes()).hexdigest()})
    return first,confirm

def accounts(market,guard,first,confirm):
    variants=[('baseline_2r',first,2.),('target_1r',first,1.),('target_1_5r',first,1.5),('confirm_1r',confirm,1.)]
    scenarios=[('main',.0005,.0005,0),('double',.001,.001,0),('delay1',.0005,.0005,1)]
    periods=[('may_jul','2026-05-01','2026-07-31'),('aug_oct','2026-08-01','2026-10-31'),('full','2026-05-01','2026-10-31')]
    out=[]
    for period,start,end in periods:
      for name,sig,target in variants:
       for tag,fee,slip,delay in scenarios:
        sc={'id':tag,'fee':fee,'slippage':slip,'delay_minutes':delay,'target_r':target}
        summary,curve,trades,entries,funding=eng.simulate(sc,sig,start,end,market=market,guard=guard,save=False,run_id=name)
        summary['period']=period;summary['target_r']=target
        summary['net_win_rate_pct']=summary['win_rate'] if trades else None
        if len(curve):
            days=(curve.ts.to_numpy()-1)//86_400_000
            summary['active_calendar_days']=int(pd.DataFrame({'day':days,'active':curve.active_in_minute}).groupby('day').active.any().sum())
        else:summary['active_calendar_days']=0
        summary['entered_within_original_quarter']=sum(int(e['ts']<(e['break_ts']//Q+1)*Q) for e in entries)
        if summary['valid_for_comparison']:
            if abs(summary['final_equity']-1000-sum(t['net'] for t in trades))>1e-6:raise ValueError('account ledger mismatch')
            if abs(sum(t['funding'] for t in trades)-sum(f['actual_charge'] for f in funding))>1e-6:raise ValueError('funding ledger mismatch')
        summary['acceptance_pass']=bool(summary['valid_for_comparison'] and len(trades)>=100 and
            summary['active_calendar_days']>=30 and summary['net_win_rate_pct'] is not None and
            summary['net_win_rate_pct']>=60 and summary['net_pnl']>0 and
            summary['profit_factor'] is not None and summary['profit_factor']>1 and summary['max_drawdown']<=15)
        stem=f'{period}_{name}_{tag}'
        dump(HERE/f'{stem}_summary.json',summary);dump(HERE/f'{stem}_trades.json',trades)
        dump(HERE/f'{stem}_entries.json',entries);dump(HERE/f'{stem}_funding.json',funding)
        curve.to_parquet(WORK/f'{stem}_curve.parquet',index=False)
        out.append(summary)
        print('ACCOUNT',stem,json.dumps({k:summary.get(k) for k in ['signal_candidates','trades','net_win_rate_pct','net_pnl','max_drawdown','valid_for_comparison','issues']}),flush=True)
    dump(HERE/'全部账户结果.json',out)
    columns=['period','run_id','scenario','signal_candidates','trades','net_win_rate_pct','net_pnl','return_pct',
             'max_drawdown','intrabar_stress_dd','profit_factor','active_calendar_days',
             'entered_within_original_quarter','valid_for_comparison','acceptance_pass','issues']
    pd.DataFrame(out).reindex(columns=columns).to_csv(HERE/'完整回测对照.csv',index=False,encoding='utf-8-sig')
    print('FORWARD_EXPERIMENT_COMPLETE',flush=True)

if __name__=='__main__':
    market=FixedMarket();guard=FixedGuard(market)
    validate_warm_features(guard)
    first,confirmed=create_signals(market,guard)
    accounts(market,guard,first,confirmed)
