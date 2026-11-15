"""Causal first-pullback state machine. No profitability-based choices."""
from common import ROOT,SOURCE,read,dump,load_contract
import numpy as np
import pandas as pd
M=60000;H=3600000

def frame(raw):
    d=raw.reindex(pd.date_range(raw.index.min(),raw.index.max(),freq='min')).copy()
    ok=d[['open','high','low','close']].gt(0).all(axis=1)&d.volume.gt(0)
    clean=d[['open','high','low','close','quote_volume']].where(ok)
    hour=clean.resample('1h',label='right',closed='left').agg({'close':'last','quote_volume':'sum'})
    good=ok.resample('1h',label='right',closed='left').sum().eq(60)
    hour=hour.where(good)
    returns=np.log(hour.close).diff()
    hour['score']=np.log(hour.close/hour.close.shift(6))/returns.rolling(24,min_periods=24).std(ddof=1)
    historical=pd.concat([hour.quote_volume.shift(24*k) for k in range(1,21)],axis=1)
    median=historical.median(axis=1).where(historical.notna().all(axis=1)&historical.gt(0).all(axis=1))
    hour['rvol']=hour.quote_volume/median
    hour['ts']=hour.index.as_unit('ms').asi8
    quarter=clean.resample('15min',label='right',closed='left').agg({'high':'max','low':'min','close':'last'})
    qgood=ok.resample('15min',label='right',closed='left').sum().eq(15)
    quarter=quarter.where(qgood)
    ema=quarter.close.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
    tr=pd.concat([quarter.high-quarter.low,(quarter.high-quarter.close.shift()).abs(),(quarter.low-quarter.close.shift()).abs()],axis=1).max(axis=1).where(qgood)
    quarter['atr']=tr.rolling(14,min_periods=14).mean()
    quarter['direction']=np.select([quarter.close.gt(ema)&ema.gt(ema.shift()),quarter.close.lt(ema)&ema.lt(ema.shift())],[1,-1],0)
    quarter['direction']=quarter.direction.where(qgood,0)
    closed=d.index+pd.Timedelta(minutes=1)
    trend=quarter[['direction','atr']].reindex(closed,method='ffill')
    out=clean.copy();out['ts']=closed.as_unit('ms').asi8;out['direction']=trend.direction.to_numpy();out['atr']=trend.atr.to_numpy()
    out['prior_high']=clean.high.shift().rolling(20,min_periods=20).max()
    out['prior_low']=clean.low.shift().rolling(20,min_periods=20).min()
    out['valid']=ok.to_numpy()
    # Drop unfinished aggregate bars before they enter any stored dataset.
    hour=hour[hour.index<=closed.max()];quarter=quarter[quarter.index<=closed.max()]
    return out,hour,quarter

def signals_for(d, ranks, symbol, contract):
    records=[];counts={'breakouts':0,'pullbacks':0,'confirmations':0,'expired':0,'invalidated':0}
    a=d[['ts','close','high','low','quote_volume','direction','atr','prior_high','prior_low','valid']].to_numpy(float)
    state=None;previous_break=0
    for j,row in enumerate(a):
        ts,close,high,low,vol,side,atr,ph,pl,valid=row;ts=int(ts);side=int(side) if np.isfinite(side) else 0
        if not valid or not np.isfinite([close,high,low,atr,ph,pl]).all() or atr<=0:
            state=None;previous_break=0;continue
        rank=ranks.get((ts//H*H,symbol,side))
        event=side if ((side==1 and close>ph) or (side==-1 and close<pl)) else 0
        fresh=event!=0 and event!=previous_break;previous_break=event
        if state is not None:
            s=state;sg=s['side'];B=s['level'];A=s['atr']
            if ts-s['break_ts']>15*M:
                counts['expired']+=1;state=None
            elif side!=sg or rank is None or sg*(close-B)<-.25*A:
                counts['invalidated']+=1;state=None
            else:
                if s['touch_ts'] is None and low<=B+.25*A and high>=B-.25*A:
                    s['touch_ts']=ts;s['extreme']=low if sg==1 else high;counts['pullbacks']+=1
                if s['touch_ts'] is not None:
                    s['extreme']=min(s['extreme'],low) if sg==1 else max(s['extreme'],high)
                    confirmed=ts>s['touch_ts'] and sg*(close-B)>0 and (close>a[j-1,2] if sg==1 else close<a[j-1,3])
                    if confirmed:
                        stop=s['extreme']-sg*.1*A
                        records.append(dict(ts=ts,symbol=symbol,contract=contract,side=sg,signal_close=close,
                            atr=A,stop_price=stop,level=B,break_ts=s['break_ts'],touch_ts=s['touch_ts'],
                            previous_quote_volume=vol,hour=ts//H*H,score=rank['score'],rank=rank['rank'],rvol=rank['rvol']))
                        counts['confirmations']+=1;state=None
            # Terminal event cannot create a second opportunity in the same bar.
            continue
        if fresh and rank is not None:
            counts['breakouts']+=1
            state=dict(side=side,level=ph if side==1 else pl,atr=atr,break_ts=ts,touch_ts=None)
    return pd.DataFrame(records),counts

def build():
    plan=read(SOURCE/'data-plan.json');pool=read(SOURCE/'daily-pools.json');quarantine=read(SOURCE/'quarantine.json')
    spec=read(ROOT/'protocol.json');start=int(pd.Timestamp(spec['start'],tz='UTC').timestamp()*1000);end=int((pd.Timestamp(spec['end'],tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    pools={x['date']:{y['symbol']:i for i,y in enumerate(x['pool'])} for x in pool}
    hours=[];quarters=[]
    for i,(s,c) in enumerate(plan['mapping'].items()):
        if not c:continue
        raw=load_contract(c,'klines')
        if raw.empty:continue
        _,h,q=frame(raw);h['symbol']=s;h['contract']=c;hours.append(h.reset_index(drop=True))
        q=q[['direction','atr']].copy();q['ts']=q.index.as_unit('ms').asi8;q['symbol']=s;quarters.append(q.reset_index(drop=True))
        if i%10==0:print('HOURLY',i,flush=True)
    allh=pd.concat(hours,ignore_index=True).replace([np.inf,-np.inf],np.nan)
    allh.to_parquet(ROOT/'hourly.parquet',index=False)
    pd.concat(quarters,ignore_index=True).to_parquet(ROOT/'regimes.parquet',index=False)
    eligible=allh[allh.ts.ge(start)&allh.ts.lt(end)].copy()
    eligible['date']=pd.to_datetime(eligible.ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    eligible=eligible[[s in pools.get(day,{}) and ts<quarantine.get(s,{}).get('known_ts',10**18) for s,day,ts in zip(eligible.symbol,eligible.date,eligible.ts)]]
    eligible['liquidity_rank']=[pools[day][s]+1 for s,day in zip(eligible.symbol,eligible.date)]
    eligible.to_parquet(ROOT/'universe-hours.parquet',index=False)
    out=[]
    for ts,g in eligible.groupby('ts'):
        for side in [1,-1]:
            z=g[(g.score*side>0)&g.rvol.ge(1.5)].copy();z['strength']=z.score*side
            z=z.sort_values(['strength','liquidity_rank','symbol'],ascending=[False,True,True]).head(3)
            for rank,r in enumerate(z.itertuples(),1):out.append(dict(hour=int(ts),symbol=r.symbol,contract=r.contract,side=side,rank=rank,score=r.score,rvol=r.rvol,liquidity_rank=r.liquidity_rank))
    ranks=pd.DataFrame(out);ranks.to_parquet(ROOT/'hourly-ranks.parquet',index=False)
    lookup={(r['hour'],r['symbol'],r['side']):r for r in out};events=[];audit=[]
    for i,(s,c) in enumerate(plan['mapping'].items()):
        if not c:continue
        raw=load_contract(c,'klines')
        if raw.empty:continue
        d,_,_=frame(raw);d=d[d.ts.ge(start)&d.ts.lt(end)&d.ts.lt(quarantine.get(s,{}).get('known_ts',10**18))]
        signals,stats=signals_for(d,lookup,s,c)
        if len(signals):events.append(signals)
        audit.append(dict(symbol=s,**stats))
        if i%10==0:print('SIGNALS',i,flush=True)
    pd.concat(events,ignore_index=True).sort_values(['ts','symbol']).to_parquet(ROOT/'signals.parquet',index=False)
    dump(ROOT/'signal-audit.json',audit)
    print('FEATURES COMPLETE',sum(len(x) for x in events),flush=True)

if __name__=='__main__':build()
