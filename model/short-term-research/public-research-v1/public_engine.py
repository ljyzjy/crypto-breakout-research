"""Fixed public-method adaptations; independent of the running paper account."""
from pathlib import Path
from functools import lru_cache
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
RESEARCH=ROOT.parent
if str(RESEARCH) not in sys.path:sys.path.insert(0,str(RESEARCH))
import st_engine as engine

VARIANTS={
 'multi_momentum':{'name':'公开方法① · 30/60/90 日动量共识','clock':'1D','hours':24},
 'ewmac_ensemble':{'name':'公开方法② · 4 小时均线趋势组合','clock':'4h','hours':4},
 'channel_ensemble':{'name':'公开方法③ · 4 小时价格通道组合','clock':'4h','hours':4},
}

def signals(raw,variant):
    spec=VARIANTS[variant]
    idx=pd.date_range(raw.index.min(),raw.index.max(),freq='h')
    d=raw.reindex(idx)
    valid=d[['open','high','low','close','volume']].notna().all(axis=1)&d.volume.gt(0)
    x=d.close.where(valid)
    count=x.resample(spec['clock'],closed='left',label='right').count()
    c=x.resample(spec['clock'],closed='left',label='right').last().where(count.eq(spec['hours']))
    if variant=='multi_momentum':
        # Calendar days retained: a missing day is never silently removed from a lookback.
        ready=c.notna().rolling(91).sum().eq(91)
        votes=sum((c/c.shift(n)-1).gt(0).astype(int) for n in (30,60,90))
        buy=ready & votes.ge(2);sell=ready & votes.lt(2)
    elif variant=='ewmac_ensemble':
        # Public EWMAC family, shortened to 4h observations, binary equal votes.
        # Eight slow spans give seed weight < exp(-16); no fitted forecast scalars.
        ready=c.notna().rolling(1024).sum().eq(1024)
        votes=sum(c.ewm(span=a,adjust=True).mean().gt(c.ewm(span=b,adjust=True).mean()).astype(int)
                  for a,b in ((8,32),(16,64),(32,128)))
        buy=ready & votes.ge(2);sell=ready & votes.lt(2)
    else:
        ready=c.notna().rolling(480).sum().eq(480)
        components=[]
        for n in (40,80,160):
            hi=c.rolling(n).max();lo=c.rolling(n).min()
            score=(c-(hi+lo)/2)/(hi-lo).replace(0,np.nan)
            components.append(score.ewm(span=n//4,adjust=True).mean())
        score=pd.concat(components,axis=1).mean(axis=1,skipna=False)
        buy=ready & score.gt(0);sell=ready & score.le(0)
    # A labelled 04:00 aggregate only becomes available after source hour 03:00 closes.
    # Only decision boundaries carry a signal; never forward-fill a partial aggregate.
    out=pd.DataFrame({'DailyMomentum_buy':buy.fillna(False),'DailyMomentum_sell':sell.fillna(False)})
    out.index=out.index-pd.Timedelta(hours=1)
    return out.reindex(idx,fill_value=False).astype(bool)

def signal_frames(data,variant):return {s:signals(data[(s,'1h')],variant) for s in engine.SYMBOLS}

@lru_cache(maxsize=3)
def cached_signals(variant):return signal_frames(engine.inputs()[0],variant)

def simulate(start,end,variant,fee=.001,resolution='1h',delay=0,data=None,full_curve=False):
    if variant not in VARIANTS:raise ValueError('Unregistered method')
    if data is None:data=engine.inputs()[0];fs=cached_signals(variant)
    else:fs=signal_frames(data,variant)
    r=engine.simulate(start,end,'DailyMomentum',fee,resolution,delay,data=data,signal_frames=fs,full_curve=full_curve)
    r.update(mode=variant,name=VARIANTS[variant]['name'],parent_mode='DailyMomentum')
    return r

def cached_run(start,end,variant,fee=.001,resolution='1h',delay=0):
    key=engine.scenario_id(start,end,variant,fee,resolution,delay);path=ROOT/'results'/(key+'.json.gz')
    if path.exists():return engine.read(path)
    r=simulate(start,end,variant,fee,resolution,delay);r['id']=key;engine.dump(path,r);return r
