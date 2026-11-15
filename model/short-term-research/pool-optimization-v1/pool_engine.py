"""Fixed, causally generated full-universe optimization candidates."""
from pathlib import Path
from functools import lru_cache
from types import FunctionType
import sys,hashlib
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parent;OLD=ROOT.parent/'coin-lab-v1'
sys.path.insert(0,str(OLD));import automatic_engine as old
import execution
VARIANTS={
 'pool_control':{'name':'全池原策略 · 精确对照','slow':False,'gate':False,'retry':False,'volstop':False},
 'pool_slow_selection':{'name':'选币改进 · 60日趋势跳过最近7日','slow':True,'gate':False,'retry':False,'volstop':False},
 'pool_market_gate':{'name':'择时改进 · BTC方向过滤新开仓','slow':False,'gate':True,'retry':False,'volstop':False},
 'pool_weekly_retry':{'name':'择时改进 · 止损后等待下周','slow':False,'gate':False,'retry':True,'volstop':False},
 'pool_vol_stop':{'name':'分仓改进 · 波动止损与固定风险','slow':False,'gate':False,'retry':False,'volstop':True},
 'pool_combined':{'name':'预先固定组合 · 四项改动','slow':True,'gate':True,'retry':True,'volstop':True}
}

@lru_cache(maxsize=1)
def slow_rankings():
    data=old.daily();idx=pd.date_range('2024-09-01','2026-10-31',tz='UTC');slow={}
    for s,raw in data.groupby('symbol'):
        d=raw.set_index('date').reindex(idx);c=d.close.where(d.volume.gt(0)&d.quote_volume.gt(0))
        slow[s]=c.shift(7)/c.shift(60)-1
    rows=[]
    for r in old.rankings()[1]:
        prior=pd.Timestamp(r['information_through'],tz='UTC');pool=[]
        for p in r['pool']:
            ret=float(slow[p['symbol']].loc[prior]);pool.append({**p,'selection_momentum':ret,'score':ret/p['sigma']})
        ranked=sorted((p for p in pool if p['momentum']>0 and p['selection_momentum']>0 and np.isfinite(p['score'])),key=lambda p:(-p['score'],p['symbol']))
        rows.append({**r,'pool':pool,'ranked':ranked,'daily_top2':[p['symbol'] for p in ranked[:2]]})
    return rows

def selection(start,end,mode):
    trace=slow_rankings() if VARIANTS[mode]['slow'] else old.rankings()[1]
    rows=[];chosen=[]
    for r in trace:
        if not start<=r['date']<=end:continue
        if not rows or pd.Timestamp(r['date']).weekday()==0:chosen=list(r['daily_top2'])
        rows.append({**r,'selected':list(chosen)})
    return rows

def prepare(start,end,mode):
    spec=VARIANTS[mode];factors=old.rankings()[0];trace=selection(start,end,mode)
    symbols=tuple(sorted({s for r in trace for s in r['selected']})) or ('BTCUSDT',)
    index=pd.date_range(pd.Timestamp(start,tz='UTC')-pd.Timedelta(hours=1),pd.Timestamp(end,tz='UTC')+pd.Timedelta(hours=23),freq='h')
    frames={s:pd.DataFrame(False,index=index,columns=['DailyMomentum_buy','DailyMomentum_sell']) for s in symbols}
    budgets={s:pd.Series(0.,index=index) for s in symbols};stops={s:pd.Series(.04,index=index) for s in symbols}
    for r in trace:
        source=pd.Timestamp(r['date'],tz='UTC')-pd.Timedelta(hours=1);prior=source.normalize()
        btc=factors['BTCUSDT'].loc[prior,'mom'];market=bool(np.isfinite(btc) and btc>0)
        r['market_allows_entry']=market if spec['gate'] else True
        for s in symbols:
            known=factors[s].loc[prior]
            positive=bool(known['valid'] and np.isfinite(known['mom']) and known['mom']>0);chosen=s in r['selected']
            frames[s].loc[source,'DailyMomentum_buy']=bool(positive and chosen and (market or not spec['gate']))
            frames[s].loc[source,'DailyMomentum_sell']=bool(not positive or not chosen)
            sigma=known['sigma']
            if positive and np.isfinite(sigma) and sigma>0:
                distance=float(np.clip(2*sigma,.04,.20)) if spec['volstop'] else .04
                stops[s].loc[source]=distance
                budgets[s].loc[source]=min(200,4/distance) if spec['volstop'] else min(200,2/sigma)
    return symbols,frames,budgets,stops,trace

@lru_cache(maxsize=256)
def execution_data(symbol,tf):
    p=ROOT/'execution-data'/f'{symbol}-{tf}.parquet'
    if not p.exists():return old.execution_data(symbol,tf)
    manifest=old.base.read(ROOT/'execution-data-manifest.json');assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['processed'][p.name]
    return pd.read_parquet(p)

def simulate(start,end,mode,fee=.001,resolution='5m',delay=0,full_curve=False):
    symbols,frames,budgets,stops,trace=prepare(start,end,mode)
    data={(s,resolution):execution_data(s,resolution) for s in symbols}
    scope=dict(execution.simulate_path.__globals__);scope.update(SYMBOLS=symbols,POLICIES=VARIANTS,sizing_frames=lambda d,p:budgets)
    runner=FunctionType(execution.simulate_path.__code__,scope,'isolated_pool_execution',execution.simulate_path.__defaults__)
    r=runner(start,end,mode,fee,resolution,delay,data,frames,full_curve,stops)
    r.update(symbols=list(symbols),selection_trace=trace,universe_kind='historical_public_USDT_archive',risk_limit_pct=15,study_version='pool-optimization-v1')
    return old.c.enrich(r)

def cached_run(start,end,mode,fee=.001,resolution='5m',delay=0):
    key=old.base.scenario_id(start,end,mode,fee,resolution,delay)+'__POOL_OPT1';p=ROOT/'results'/(key+'.json.gz')
    if p.exists():return old.c.enrich(old.base.read(p))
    r=simulate(start,end,mode,fee,resolution,delay);r['id']=key;old.base.dump(p,r);return r

def summary(r):return {k:v for k,v in r.items() if k not in ('curve','trades','orders','selection_trace')}
