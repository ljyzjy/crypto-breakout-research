import gc
import hashlib
import pandas as pd
from types import FunctionType
import availability_engine as e
import selection_engine as original
from build_gate import discover,filter_rows


def main():
    checks=[]
    oldfreeze=e.base.read(original.ROOT/'frozen.json')
    for path,sha in oldfreeze['files'].items():
        assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha,path
    checks.append('原始规则、数据与已完成84条结果保留；未覆盖原实验')
    scope=dict(discover.__globals__);scope['original']=e
    get=FunctionType(discover.__code__,scope,argdefs=discover.__defaults__)
    gates=get(e.manifest())
    assert gates==e.base.read(e.ROOT/'quarantine.json'),'Replacement data introduced unaccounted gaps'
    for cutoff in ('2026-03-31 23:59','2026-04-01 00:04','2026-04-01 00:05','2026-04-10'):
        limit=pd.Timestamp(cutoff,tz='UTC')
        actual=get(e.manifest(),limit)
        expected={s:g for s,g in gates.items() if g['observed_ts']<=limit.timestamp()}
        assert actual==expected,(cutoff,actual,expected)
    checks.append('缺失识别通过4次未来截断：仅在缺失柱结束之后隔离；所有币统一规则')
    for selector in e.FACTOR_SELECTORS:
        source=original.hourly_history(selector)
        amended=e.hourly_history(selector)
        for a,b in zip(source,amended):
            t=pd.Timestamp(b['date']).timestamp()
            assert all(g['observed_ts']<=t for g in b['excluded_data'])
            assert not any(s in gates and gates[s]['observed_ts']<=t for s in b['daily_top2'])
            if not b['excluded_data']:assert a['daily_top2']==b['daily_top2']
        del source,amended
    e.hourly_history.cache_clear();original.hourly_history.cache_clear()
    checks.append('所有小时名单检查通过：缺失前不删币、缺失后按原评分递补、其余排名不改')
    for variant in ('fixed1','tiered'):
        a=e.cached_run('2025-01-01','2026-04-26','control_weekly__'+variant)
        b=original.cached_run('2025-01-01','2026-04-26','control_weekly__'+variant)
        for key in ('valid_for_comparison','return_pct','max_drawdown','fees','slippage_cost','funding_cost','core_pnl','boost_pnl'):
            assert a[key]==b[key],(variant,key,a[key],b[key])
    checks.append('周度1×与动态5×对照完全复现原实验；既有持仓缺价仍中止')
    sources=[e.ROOT/x for x in ('availability_engine.py','build_gate.py','protocol.json','quarantine.json','data-manifest.json','weekly-rankings.json.gz')]
    sources.extend(sorted((e.ROOT/'signals').glob('*.json.gz')))
    frozen=dict(oldfreeze['files'])
    frozen.update({str(p.relative_to(e.ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    e.base.dump(e.ROOT/'preflight.json',dict(passed=True,checks=checks))
    e.base.dump(e.ROOT/'frozen.json',dict(created_utc=pd.Timestamp.now(tz='UTC').isoformat(),files=frozen))
    print('\n'.join(checks),flush=True)
    print('Amended rules frozen before new candidate outcomes',flush=True)


if __name__=='__main__':main()
