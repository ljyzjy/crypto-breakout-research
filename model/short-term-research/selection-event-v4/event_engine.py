"""Sell-triggered replacement research; no timer/rank-based forced liquidation."""
from pathlib import Path
from functools import lru_cache
from types import FunctionType
import hashlib,sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'selection-12h-v3'))
import cadence_engine as cadence
parent=cadence.previous
base=parent.base;pd=parent.pd;np=parent.np;old=parent.old
NEW_NAMES={s+'_event__'+v:n+' · 卖出后补位'+(' · 1×' if v=='fixed1' else ' · 动态上限5×')
    for s,n in [('control','原较慢动量'),('combined','四因子等权')] for v in ('fixed1','tiered')}
NAMES={**cadence.NAMES,**NEW_NAMES}
SCENARIOS=cadence.SCENARIOS
key=parent.key;summary=parent.summary

@lru_cache(maxsize=1)
def manifest():return base.read(ROOT/'data-manifest.json')

@lru_cache(maxsize=3)
def load_frame(symbol,kind):
    item=manifest()['processed'].get(symbol+'/'+kind)
    if not item:return None
    p=ROOT.parent/item['path']
    assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
    return pd.read_parquet(p)

@lru_cache(maxsize=1)
def hourly_history(selector):return base.read(ROOT/'signals'/f'{selector}-hourly.json.gz')

def scope():
    g=dict(parent.prepare.__wrapped__.__globals__)
    g.update(ROOT=ROOT,manifest=manifest,load_frame=load_frame,hourly_history=hourly_history)
    return g

@lru_cache(maxsize=1)
def prepare(start,end,selector,delay=0):
    import event_prepare
    fn=FunctionType(event_prepare.prepare_path.__code__,scope(),argdefs=event_prepare.prepare_path.__defaults__)
    z=fn(start,end,selector.replace('_event','_hourly'),delay)
    z=cadence.clock12(z,delay)
    z['quarantine']=base.read(ROOT/'quarantine.json')
    # A held asset's timing signal must remain available after it leaves the
    # top20 qualification pool; rank loss itself must not masquerade as momentum0.
    hm=base.read(parent.V1/'hourly-manifest.json')
    decision_hours=(z['index']-pd.Timedelta(minutes=delay)).floor('h')
    for s in z['symbols']:
        item=hm['processed'][s];path=ROOT.parent/item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        h=pd.read_parquet(path)
        h=h.reindex(pd.date_range(h.index.min(),h.index.max(),freq='h'))
        c=h.close.where(h.volume.gt(0));momentum=c/c.shift(30*24)-1
        momentum.index=momentum.index+pd.Timedelta(hours=1)
        m=momentum.reindex(decision_hours).to_numpy(float)
        z['mom'][s]=np.where(np.isfinite(m)&(m>0),1,0).astype(np.int8)
    parent.hourly_panel.cache_clear()
    return z

@lru_cache(maxsize=1)
def features():
    fn=FunctionType(parent.leverage_features.__wrapped__.__code__,scope())
    return fn()

def simulate(start,end,mode,fee=.0005,delay=0,fixture=None,feature_fixture=None):
    if mode not in NEW_NAMES:return cadence.simulate(start,end,mode,fee,delay,fixture,feature_fixture)
    from event_execution import simulate_path
    z=fixture if fixture is not None else prepare(start,end,mode.split('__')[0],delay)
    g=dict(parent.previous.simulate.__globals__);g.update(NAMES=NAMES,hourly_rotation=True)
    fn=FunctionType(simulate_path.__code__,g,argdefs=simulate_path.__defaults__)
    r=fn(start,end,mode,fee,delay,z,feature_fixture if feature_fixture is not None else features())
    r.update(research_version='selection-event-v4',history_seen=True)
    return r

def cached_run(start,end,mode,fee=.0005,delay=0):
    if mode not in NEW_NAMES:return cadence.cached_run(start,end,mode,fee,delay)
    ident=key(start,end,mode,fee,delay);p=ROOT/'results'/(ident+'.json.gz')
    if p.exists():return base.read(p)
    r=simulate(start,end,mode,fee,delay);r['id']=ident;base.dump(p,r);return r
