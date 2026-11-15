"""Causal rolling public universe, explicit weekly choices and isolated execution."""
from pathlib import Path
from types import FunctionType
from functools import lru_cache
import hashlib,json,sys
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parent
import coin_engine as c
base,risk=c.base,c.risk
AUTO={'auto_budget2':{'name':'全池自动选币 · 波动预算2 U','candidate':True},'auto_budget3':{'name':'全池自动选币 · 波动预算3 U','candidate':True}}

@lru_cache(maxsize=1)
def daily():
    manifest=base.read(ROOT/'pool-data-manifest.json');p=ROOT/'pool-daily.parquet'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['pool_sha256']
    return pd.read_parquet(p)

def rank_history(frame):
    """Rows dated D use only observations with open date <=D-1."""
    assert frame.date.between(pd.Timestamp('2024-09-01',tz='UTC'),pd.Timestamp('2026-10-31',tz='UTC')).all()
    spec=base.read(ROOT/'automatic-protocol.json');symbols=sorted(frame.symbol.unique())
    excluded={s+'USDT' for s in spec['exclusions']}
    assetset={s[:-4] for s in symbols}
    for a in assetset:
        for suffix,other in [('UP','DOWN'),('DOWN','UP'),('BULL','BEAR'),('BEAR','BULL')]:
            if a.endswith(suffix) and a[:-len(suffix)]+other in assetset:excluded.add(a+'USDT')
    idx=pd.date_range(pd.Timestamp('2024-09-01',tz='UTC'),frame.date.max(),freq='D')
    candidates={};byday={}
    for s,raw in frame.groupby('symbol'):
        if s in excluded:continue
        d=raw.set_index('date').reindex(idx);close=d.close.where(d.volume.gt(0)&d.quote_volume.gt(0))
        vol=np.log(close).diff().rolling(20,min_periods=20).std(ddof=1)
        mom=close/close.shift(30)-1;liquidity=d.quote_volume.where(close.notna()).rolling(30).median()
        eligible=close.notna().rolling(90).sum().eq(90)&liquidity.ge(10_000_000)&vol.gt(0)
        eligible &= (idx>=pd.Timestamp('2024-12-31',tz='UTC')) & (idx<=pd.Timestamp('2026-10-30',tz='UTC'))
        values=pd.DataFrame({'liquidity':liquidity,'momentum':mom,'sigma':vol})[eligible]
        values.index=values.index+pd.Timedelta(days=1)
        for when,liq,ret,sigma in values.itertuples(name=None):
            byday.setdefault(when,[]).append({'symbol':s,'median_volume':float(liq),'momentum':float(ret),'sigma':float(sigma),'score':float(ret/sigma)})
        candidates[s]=pd.DataFrame({'mom':mom,'sigma':vol,'valid':close.notna()},index=idx)
    trace=[]
    for day in pd.date_range(pd.Timestamp('2025-01-01',tz='UTC'),min(pd.Timestamp('2026-10-31',tz='UTC'),frame.date.max()+pd.Timedelta(days=1))):
        a=sorted(byday.get(day,[]),key=lambda r:(-r['median_volume'],r['symbol']));pool=a[:20]
        ranked=sorted((r for r in pool if r['momentum']>0),key=lambda r:(-r['score'],r['symbol']))
        trace.append({'date':day.strftime('%Y-%m-%d'),'information_through':(day-pd.Timedelta(days=1)).strftime('%Y-%m-%d'),'eligible_count':len(a),'pool':pool,'ranked':ranked,'daily_top2':[r['symbol'] for r in ranked[:2]]})
    return candidates,trace,sorted(excluded)

@lru_cache(maxsize=1)
def rankings():return rank_history(daily())

def selection(start,end):
    _,trace,_=rankings();chosen=[];rows=[]
    for r in trace:
        if not start<=r['date']<=end:continue
        if not rows or pd.Timestamp(r['date']).weekday()==0:chosen=list(r['daily_top2'])
        rows.append({**r,'selected':list(chosen)})
    return rows

@lru_cache(maxsize=128)
def execution_data(symbol,tf):
    if symbol in base.SYMBOLS:return base.inputs()[0][(symbol,tf)]
    p=ROOT/'execution'/f'{symbol}-{tf}.parquet'
    manifest=base.read(ROOT/'execution-manifest.json')
    assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['processed'][p.name]
    return pd.read_parquet(p)

def prepare(start,end,policy):
    factors,_,_=rankings();trace=selection(start,end)
    symbols=tuple(sorted({s for r in trace for s in r['selected']}))
    # Empty selection still returns a valid, cash-only path with BTC as an inert carrier.
    if not symbols:symbols=('BTCUSDT',)
    index=pd.date_range(pd.Timestamp(start,tz='UTC')-pd.Timedelta(hours=1),pd.Timestamp(end,tz='UTC')+pd.Timedelta(hours=23),freq='h')
    frames={s:pd.DataFrame(False,index=index,columns=['DailyMomentum_buy','DailyMomentum_sell']) for s in symbols}
    budgets={s:pd.Series(0.,index=index) for s in symbols}
    amount=2 if policy=='auto_budget2' else 3;cap=amount*100
    for r in trace:
        source=pd.Timestamp(r['date'],tz='UTC')-pd.Timedelta(hours=1);prior=source.normalize()
        for s in symbols:
            f=factors.get(s);known=f.loc[prior] if f is not None and prior in f.index else None
            positive=bool(known is not None and known['valid'] and np.isfinite(known['mom']) and known['mom']>0)
            selected=s in r['selected']
            frames[s].loc[source,'DailyMomentum_buy']=bool(selected and positive)
            frames[s].loc[source,'DailyMomentum_sell']=bool(not selected or not positive)
            if positive and np.isfinite(known['sigma']) and known['sigma']>0:budgets[s].loc[source]=min(cap,amount/known['sigma'])
    return symbols,frames,budgets,trace

def simulate(start,end,policy,fee=.001,resolution='1h',delay=0,full_curve=False):
    if policy not in AUTO:raise ValueError('Unknown automatic policy')
    symbols,frames,budgets,trace=prepare(start,end,policy)
    raw={(s,resolution):execution_data(s,resolution) for s in symbols}
    scope=dict(risk.simulate.__globals__)
    scope.update(SYMBOLS=symbols,POLICIES=AUTO,sizing_frames=lambda d,p:budgets)
    runner=FunctionType(risk.simulate.__code__,scope,'automatic_simulate',risk.simulate.__defaults__)
    r=runner(start,end,policy,fee,resolution,delay,raw,frames,full_curve)
    r.update(symbols=list(symbols),selection_trace=trace,universe_kind='historical_public_USDT_archive',risk_limit_pct=15)
    return c.enrich(r)

def cached_run(start,end,policy,fee=.001,resolution='1h',delay=0):
    key=base.scenario_id(start,end,policy,fee,resolution,delay)+'__AUTO';path=ROOT/'results'/(key+'.json.gz')
    if path.exists():return c.enrich(base.read(path))
    r=simulate(start,end,policy,fee,resolution,delay);r['id']=key;base.dump(path,r);return r
