"""Backward-only minute signals. Signal timestamps mean information is now closed."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from prepare_data import ROOT,RESEARCH,read,dump,sha

def load_contract(contract,kind,through=None):
    paths=sorted((ROOT/'data'/kind/contract).glob('*.parquet'))
    chunks=[pd.read_parquet(p) for p in paths]
    if not chunks:return pd.DataFrame()
    d=pd.concat(chunks,ignore_index=True).sort_values('ts')
    if through is not None:d=d[d.ts<=through]
    assert not d.ts.duplicated().any()
    d.index=pd.to_datetime(d.ts,unit='ms',utc=True)
    return d

def make_features(raw):
    """Output candidates and hourly ranks, all indexed by the close/decision timestamp."""
    if raw.empty:return pd.DataFrame(),pd.DataFrame()
    ix=pd.date_range(raw.index.min(),raw.index.max(),freq='min')
    d=raw.reindex(ix)
    valid=d[['open','high','low','close']].gt(0).all(axis=1)&d.volume.gt(0)
    clean=d[['open','high','low','close','quote_volume']].where(valid)
    h=clean.resample('1h',label='right',closed='left').agg({'close':'last'})
    hc=valid.resample('1h',label='right',closed='left').sum().eq(60)
    h['close']=h.close.where(hc)
    hr=np.log(h.close).diff()
    h['score']=np.log(h.close/h.close.shift(6))/hr.rolling(24,min_periods=24).std(ddof=1)
    h['score']=h.score.where(np.isfinite(h.score))
    f=clean.resample('15min',label='right',closed='left').agg({'high':'max','low':'min','close':'last'})
    fc=valid.resample('15min',label='right',closed='left').sum().eq(15)
    f=f.where(fc)
    ema=f.close.ewm(span=20,adjust=False,min_periods=20,ignore_na=False).mean()
    tr=pd.concat([f.high-f.low,(f.high-f.close.shift()).abs(),(f.low-f.close.shift()).abs()],axis=1).max(axis=1).where(fc)
    f['atr']=tr.rolling(14,min_periods=14).mean()
    f['direction']=np.select([f.close.gt(ema)&ema.gt(ema.shift()),f.close.lt(ema)&ema.lt(ema.shift())],[1,-1],0)
    f['direction']=f.direction.where(fc,0)
    closed=d.index+pd.Timedelta(minutes=1)
    preceding_hi=clean.high.shift().rolling(20,min_periods=20).max()
    preceding_lo=clean.low.shift().rolling(20,min_periods=20).min()
    vmed=clean.quote_volume.shift().rolling(20,min_periods=20).median()
    trend=f[['atr','direction']].reindex(closed,method='ffill')
    side=trend.direction.to_numpy()
    hit=((side==1)&d.close.gt(preceding_hi).to_numpy())|((side==-1)&d.close.lt(preceding_lo).to_numpy())
    atr=trend.atr.to_numpy()
    cost_gate=(3*atr/d.close.to_numpy())>=.006
    mask=hit&valid.to_numpy()&d.quote_volume.ge(1.5*vmed).to_numpy()&cost_gate&np.isfinite(atr)&(atr>0)
    candidates=pd.DataFrame({'ts':closed.as_unit('ms').asi8,'side':side,'signal_close':d.close.to_numpy(),
       'atr':atr,'previous_quote_volume':d.quote_volume.to_numpy(),
       'source_open_ts':d.index.as_unit('ms').asi8})[mask]
    candidates['hour']=candidates.ts//3_600_000*3_600_000
    h['ts']=h.index.as_unit('ms').asi8
    return candidates.reset_index(drop=True),h[['ts','score']].dropna().reset_index(drop=True)

def first_gap(symbol,contract,raw,plan):
    if raw.empty:return None
    mark=load_contract(contract,'markPriceKlines')
    if mark.empty:return {'symbol':symbol,'known_ts':int(raw.ts.min()+60_000),'reason':'no_mark_after_first_trade'}
    expected=pd.DatetimeIndex([])
    spans=[pd.date_range(d,periods=1440,freq='min',tz='UTC') for d in plan['days'][symbol]]
    expected=spans[0].append(spans[1:])
    trade=raw.reindex(expected)
    mk=mark.reindex(expected)
    good=trade.close.gt(0)&trade.volume.gt(0)&mk.close.gt(0)
    if not good.any():return {'symbol':symbol,'known_ts':int(expected[0].timestamp()*1000+60_000),'reason':'no_joint_trade_mark'}
    # Zero volume is ineligible, not proof of a missing archive. Missing OHLC is a data gap.
    absent=trade.close.isna()|mk.close.isna()
    bad=absent & (expected>good[good].index[0])
    if not bad.any():return None
    t=bad[bad].index[0]
    return {'symbol':symbol,'known_ts':int(t.timestamp()*1000+60_000),'missing_open':t.isoformat(),'reason':'missing_completed_trade_or_mark'}

def build():
    plan=read(ROOT/'data-plan.json');pools=read(ROOT/'daily-pools.json');spec=read(ROOT/'protocol.json')
    start=int(pd.Timestamp(spec['start'],tz='UTC').timestamp()*1000)
    end=int((pd.Timestamp(spec['end'],tz='UTC')+pd.Timedelta(days=1)).timestamp()*1000)
    signals=[];hours=[];quarantine={};coverage=[]
    previous=read(RESEARCH/'selection-data-gate-v2/quarantine.json')
    for i,(s,c) in enumerate(plan['mapping'].items(),1):
        if c is None:coverage.append({'symbol':s,'status':'no_historical_matching_perpetual'});continue
        d=load_contract(c,'klines')
        if d.empty:coverage.append({'symbol':s,'status':'no_minute_archives'});continue
        q=first_gap(s,c,d,plan)
        if s in previous:
            old={'symbol':s,'known_ts':previous[s]['observed_ts']*1000,'reason':'prior_observed_quarantine'}
            if q is None or old['known_ts']<q['known_ts']:q=old
        if q:quarantine[s]=q
        candidate,h=make_features(d)
        candidate['symbol']=s;candidate['contract']=c
        h['symbol']=s
        candidate=candidate[candidate.ts.ge(start)&candidate.ts.lt(end)]
        h=h[h.ts.ge(start)&h.ts.lt(end)]
        if q:candidate=candidate[candidate.ts<q['known_ts']];h=h[h.ts<q['known_ts']]
        signals.append(candidate);hours.append(h)
        coverage.append({'symbol':s,'contract':c,'minute_rows':len(d),'raw_technical_candidates':len(candidate),
                         'quarantine':q})
        if i%10==0:print('FEATURES',i,'/',len(plan['mapping']),flush=True)
    allh=pd.concat(hours,ignore_index=True)
    poolmap={r['date']:{p['symbol'] for p in r['pool']} for r in pools}
    allh['date']=pd.to_datetime(allh.ts,unit='ms',utc=True).dt.strftime('%Y-%m-%d')
    allh=allh[[s in poolmap.get(day,set()) for s,day in zip(allh.symbol,allh.date)]]
    ranked=[]
    for t,g in allh.groupby('ts',sort=True):
        for side in (1,-1):
            a=g[g.score*side>0].copy();a['strength']=a.score*side
            a=a.sort_values(['strength','symbol'],ascending=[False,True]).head(3)
            for rank,row in enumerate(a.itertuples(),1):ranked.append({'hour':int(t),'symbol':row.symbol,'side':side,'score':float(row.score),'rank':rank})
    ranks=pd.DataFrame(ranked)
    signals=pd.concat(signals,ignore_index=True)
    merged=signals.merge(ranks,on=['hour','symbol','side'],how='inner').sort_values(['ts','rank','symbol'])
    merged.to_parquet(ROOT/'signals.parquet',index=False)
    ranks.to_parquet(ROOT/'hourly-ranks.parquet',index=False)
    dump(ROOT/'quarantine.json',quarantine);dump(ROOT/'coverage.json',coverage)
    dump(ROOT/'feature-manifest.json',{'signals_sha256':sha(ROOT/'signals.parquet'),'ranks_sha256':sha(ROOT/'hourly-ranks.parquet'),
       'signal_count':len(merged),'rank_rows':len(ranks),'symbols':len(plan['mapping']),'quarantined':len(quarantine),
       'price_source':'USDT perpetual1m','no_future_information':True})
    print('FEATURES READY',len(merged),'candidates',len(quarantine),'quarantined',flush=True)

if __name__=='__main__':build()
