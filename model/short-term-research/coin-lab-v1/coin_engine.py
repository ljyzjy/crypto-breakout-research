"""Isolated symbol/budget adapter over the frozen, tested execution function."""
from pathlib import Path
from functools import lru_cache
from types import FunctionType
import sys,hashlib,json
import pandas as pd
ROOT=Path(__file__).resolve().parent
RESEARCH=ROOT.parent
for p in (RESEARCH,RESEARCH/'risk-budget-v1',RESEARCH.parent/'dashboard'):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
import st_engine as base
import risk_engine as risk
from performance_metrics import enrich
SYMBOLS=('BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT')
POLICIES={**risk.POLICIES,
 'vol_budget3':{'name':'增额试验 · 波动预算3 U / 上限300 U','candidate':True},
 'vol_budget4':{'name':'增额试验 · 波动预算4 U / 上限400 U','candidate':True}}

def normalize(symbols):
    if not 1<=len(symbols)<=2 or len(set(symbols))!=len(symbols) or any(s not in SYMBOLS for s in symbols):
        raise ValueError('请选择1至2个已支持币种，不能重复')
    return tuple(s for s in SYMBOLS if s in symbols)

@lru_cache(maxsize=5)
def coin_data(symbol):
    if symbol in base.SYMBOLS:
        raw,features=base.inputs()
        return {tf:raw[(symbol,tf)] for tf in ('1h','5m')},features[symbol]
    manifest=base.read(ROOT/'data-manifest.json')
    raw={}
    for tf in ('1h','5m'):
        filename=f'{symbol}-{tf}.parquet';p=ROOT/'processed'/filename
        if hashlib.sha256(p.read_bytes()).hexdigest()!=manifest['processed'][filename]:
            raise ValueError('Processed data hash mismatch')
        raw[tf]=pd.read_parquet(p)
    return raw,base.features(raw['1h'])

def inputs(symbols):
    raw={};frames={}
    for s in symbols:
        a,f=coin_data(s);raw.update({(s,tf):d for tf,d in a.items()});frames[s]=f
    return raw,frames

def sizes(data,policy,symbols):
    idx=data[(symbols[0],'1h')].index
    if policy in ('fixed100','fixed200'):
        return {s:pd.Series(100. if policy=='fixed100' else 200.,index=idx) for s in symbols}
    sigma=pd.DataFrame({s:risk.daily_vol(data[(s,'1h')]) for s in symbols})
    if policy=='inverse_vol_pair':
        inv=1/sigma
        stake=(200*inv.div(inv.sum(axis=1,min_count=len(symbols)),axis=0)).clip(upper=150)
    else:
        budget,cap={'vol_cap100':(2,100),'vol_target200':(2,200),'vol_budget3':(3,300),'vol_budget4':(4,400)}[policy]
        stake=(budget/sigma).clip(upper=cap)
    return {s:stake[s].fillna(0) for s in symbols}

def simulate(start,end,policy,fee=.001,resolution='1h',delay=0,symbols=('BTCUSDT','ETHUSDT'),data=None,signal_frames=None,full_curve=False):
    symbols=normalize(symbols)
    if data is None:data,signal_frames=inputs(symbols)
    # A private global mapping per call: no global mutation, shared thread or bot state.
    scope=dict(risk.simulate.__globals__)
    scope.update(SYMBOLS=symbols,POLICIES=POLICIES,sizing_frames=lambda d,p:sizes(d,p,symbols))
    runner=FunctionType(risk.simulate.__code__,scope,'isolated_simulate',risk.simulate.__defaults__)
    r=runner(start,end,policy,fee,resolution,delay,data,signal_frames,full_curve)
    r.update(symbols=list(symbols),universe_kind='manual_research_selection',risk_limit_pct=15)
    return enrich(r)

def scenario_id(start,end,policy,fee,resolution,delay,symbols):
    return base.scenario_id(start,end,policy,fee,resolution,delay)+'__'+'-'.join(normalize(symbols))

def cached_run(start,end,policy,fee=.001,resolution='1h',delay=0,symbols=('BTCUSDT','ETHUSDT')):
    key=scenario_id(start,end,policy,fee,resolution,delay,symbols);path=ROOT/'results'/(key+'.json.gz')
    if path.exists():return enrich(base.read(path))
    r=simulate(start,end,policy,fee,resolution,delay,symbols);r['id']=key;base.dump(path,r);return r

def summary(r):return {k:v for k,v in r.items() if k not in ('orders','trades','curve')}
