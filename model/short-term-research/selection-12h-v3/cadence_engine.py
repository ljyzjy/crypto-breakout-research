"""User-requested12h decision clock, with every frozen factor/cost/risk rule retained."""
from pathlib import Path
from functools import lru_cache
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'selection-data-gate-v2'))
import availability_engine as previous
base=previous.base
pd=previous.pd
np=previous.np
NEW_NAMES={s+'_12h__'+v:n+' · 每12小时选币'+(' · 1×' if v=='fixed1' else ' · 动态上限5×')
           for s,n in previous.FACTOR_SELECTORS.items() for v in ('fixed1','tiered')}
NAMES={**previous.NAMES,**NEW_NAMES}
SCENARIOS=base.read(previous.ROOT/'official-protocol.json')['cost_scenarios']
hourly_history=previous.hourly_history
summary=previous.summary
key=previous.key


def clock12(z,delay):
    info=z['index']-pd.Timedelta(minutes=delay)
    return {**z,'decision':z['decision'] & np.asarray(info.hour%12==0)}


@lru_cache(maxsize=1)
def prepare(start,end,selector,delay=0):
    original=selector.replace('_12h','_hourly')
    return clock12(previous.prepare(start,end,original,delay),delay)


def simulate(start,end,mode,fee=.0005,delay=0,fixture=None,feature_fixture=None):
    if mode not in NEW_NAMES:return previous.simulate(start,end,mode,fee,delay,fixture,feature_fixture)
    selector,variant=mode.split('__')
    z=clock12(fixture,delay) if fixture is not None else prepare(start,end,selector,delay)
    r=previous.simulate(start,end,mode.replace('_12h__','_hourly__'),fee,delay,z,feature_fixture)
    r.update(mode=mode,name=NAMES[mode],selector=selector,research_version='selection-12h-v3',rotation_hours=12)
    return r


def cached_run(start,end,mode,fee=.0005,delay=0):
    if mode not in NEW_NAMES:return previous.cached_run(start,end,mode,fee,delay)
    ident=key(start,end,mode,fee,delay);p=ROOT/'results'/(ident+'.json.gz')
    if p.exists():return base.read(p)
    r=simulate(start,end,mode,fee,delay);r['id']=ident;base.dump(p,r)
    return r
