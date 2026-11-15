"""Three preregistered entry-only variants, using the unmodified frozen execution engine."""
from pathlib import Path
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parent
RESEARCH=ROOT.parent
if str(RESEARCH) not in sys.path:sys.path.insert(0,str(RESEARCH))
import st_engine as engine

VARIANTS={
    'breakout_mom30':{'parent':'breakout','name':'A 优化① · 个币方向过滤'},
    'breakout_4h_entry':{'parent':'breakout','name':'A 优化② · 每四小时入场'},
    'reversion_cost_room':{'parent':'reversion','name':'C 优化③ · 成本空间过滤'},
}

def cost_threshold(fee,slippage=.0005):
    return (1+slippage)*(1+fee)/((1-slippage)*(1-fee))-1

def completed_daily_momentum(raw,index):
    # Each daily close becomes available at its right edge, after the final hour closes.
    daily=raw.close.resample('1D',closed='left',label='right').last()
    count=raw.close.resample('1D',closed='left',label='right').count()
    daily=daily[count.eq(24)]
    momentum=daily/daily.shift(30)-1
    return pd.Series(momentum.to_numpy(),index=momentum.index-pd.Timedelta(hours=1)).reindex(index).ffill()

def signal_frames(data,original,variant,fee=.001):
    parent=VARIANTS[variant]['parent'];result={}
    for symbol in engine.SYMBOLS:
        f=original[symbol].copy(deep=True)
        raw=data[(symbol,'1h')].reindex(f.index)
        if variant=='breakout_mom30':
            eligible=completed_daily_momentum(raw,f.index).gt(0)
        elif variant=='breakout_4h_entry':
            # Source bar 03:00-04:00 can be used at the 04:00 decision (or 04:05 delayed fill).
            eligible=(f.index+pd.Timedelta(hours=1)).hour%4==0
        elif variant=='reversion_cost_room':
            eligible=(f.vwap24/raw.close-1).gt(cost_threshold(fee))
        f[parent+'_buy']=f[parent+'_buy']&eligible
        result[symbol]=f
    return result

def simulate(start,end,variant,fee=.001,resolution='1h',delay=0,data=None,original=None):
    if variant not in VARIANTS:raise ValueError('Unknown registered variant')
    if data is None:data,original=engine.inputs()
    if original is None:original={s:engine.features(data[(s,'1h')]) for s in engine.SYMBOLS}
    fs=signal_frames(data,original,variant,fee)
    parent=VARIANTS[variant]['parent']
    r=engine.simulate(start,end,parent,fee,resolution,delay,data=data,signal_frames=fs)
    r.update(mode=variant,parent_mode=parent,name=VARIANTS[variant]['name'],
             cost_room_threshold_pct=cost_threshold(fee)*100 if variant=='reversion_cost_room' else None)
    return r

def scenario_id(start,end,variant,fee,resolution,delay=0):
    return engine.scenario_id(start,end,variant,fee,resolution,delay)

def cached_run(start,end,variant,fee=.001,resolution='1h',delay=0):
    key=scenario_id(start,end,variant,fee,resolution,delay)
    path=ROOT/'results'/(key+'.json.gz')
    if path.exists():return engine.read(path)
    result=simulate(start,end,variant,fee,resolution,delay)
    result['id']=key;engine.dump(path,result)
    return result
