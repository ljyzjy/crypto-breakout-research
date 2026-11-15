"""Economic control reproduction and causal timing checks before new outcomes."""
import gc
import hashlib
import numpy as np
import pandas as pd
import selection_engine as e
from test_dynamic import fixture as seed_fixture


def synthetic(hourly=True):
    z,f = seed_fixture()
    z['symbols'] = e.previous.seed.SYMBOLS
    z['trace'] = {}
    for t in pd.date_range('2025-01-01','2025-01-04 23:00',freq='h',tz='UTC'):
        z['trace'][int(t.timestamp())] = dict(date=t.isoformat(),daily_top2=['BTCUSDT'],ranked=[{'symbol':'BTCUSDT'}])
    return z,f


def main():
    checks = []
    z,f = synthetic()
    r = e.simulate('2025-01-01','2025-01-04','control_hourly__tiered',fixture=z,feature_fixture=f)
    adds = [o for o in r['orders'] if o['reason']=='leverage_add']
    assert len(adds)==8 and all(o['ts']%86400==0 and o['stop_risk_pct']<=2 for o in adds)
    assert r['core_trades']==1, 'Hourly evaluation must not force hourly turnover'
    z,f=synthetic()
    t=int(pd.Timestamp('2025-01-01 01:00',tz='UTC').timestamp())
    for stamp,row in z['trace'].items():
        if stamp>=t:row['daily_top2']=[]
    r=e.simulate('2025-01-01','2025-01-04','control_hourly__fixed1',fixture=z,feature_fixture=f)
    assert r['trades'][0]['exit_ts']==t
    for which in ('previous','held'):
        z,f=synthetic()
        if which=='previous':z['avail']['BTCUSDT'][0]=2
        else:z['ok']['BTCUSDT'][300]=False
        r=e.simulate('2025-01-01','2025-01-04','combined_hourly__fixed1',fixture=z,feature_fixture=f)
        assert not r['valid_for_comparison'] and r['annualized_return_pct'] is None and r['max_drawdown'] is None
    checks.append('Hourly rotation, unchanged-name no-churn, daily-only max5 additions, 2% add-risk and missing-data rejection')
    print(checks[-1],flush=True)
    # Old weekly selection order must remain byte-for-byte equivalent in symbols.
    for a,b in zip(e.rankings()['control'],e.old.prior.slow_rankings()):
        assert a['daily_top2']==b['daily_top2'] and [x['symbol'] for x in a['ranked']]==[x['symbol'] for x in b['ranked']]
    for variant in ('fixed1','tiered'):
        a=e.simulate('2025-01-01','2026-04-26','control_weekly__'+variant)
        b=e.previous.cached_run('2025-01-01','2026-04-26','slow_base__'+variant)
        assert a['valid_for_comparison']==b['valid_for_comparison']==True
        for key in ('return_pct','max_drawdown','fees','slippage_cost','funding_cost','core_pnl','boost_pnl'):
            assert abs(a[key]-b[key])<1e-7,(variant,key,a[key],b[key])
        del a,b
    checks.append('Both weekly control paths exactly reproduce previous common-period economics')
    print(checks[-1],flush=True)
    e.prepare.cache_clear();e.leverage_features.cache_clear();gc.collect()
    from hourly_signals import load_hourly,panel_from_hourly
    data=load_hourly();full=pd.read_parquet(e.ROOT/'hourly-factors.parquet')
    history=e.old.prior.slow_rankings()
    for cutoff in ('2025-06-30','2026-03-31'):
        limit=pd.Timestamp(cutoff,tz='UTC')+pd.Timedelta(days=1)
        small={s:d.loc[d.index<limit].copy() for s,d in data.items()}
        actual=panel_from_hourly(small,history,cutoff).sort_values(['ts','symbol']).reset_index(drop=True)
        expected=full.loc[full.ts<int(limit.timestamp())].sort_values(['ts','symbol']).reset_index(drop=True)
        pd.testing.assert_frame_equal(actual,expected,check_dtype=False,rtol=1e-9,atol=1e-12)
        print('Hourly future truncation passed',cutoff,flush=True)
    checks.append('All hourly factors unchanged under two raw-input future truncations; universe comes from previous-day history')
    # Each emitted order list is based on actual past bars; no reconstructed current list.
    for selector in e.FACTOR_SELECTORS:
        for row in e.hourly_history(selector):
            t=pd.Timestamp(row['date'])
            assert pd.Timestamp(row['information_through'])+pd.Timedelta(hours=1)==t
            assert pd.Timestamp(row['universe_information_through'],tz='UTC')<t
    checks.append('Hourly signal timestamp and preceding daily universe cutoff checked for all ranking records')
    sources=[e.ROOT/'selection_engine.py',e.ROOT/'selection_execution.py',e.ROOT/'hourly_signals.py',
        e.ROOT/'protocol.json',e.ROOT/'data-manifest.json',e.ROOT/'hourly-manifest.json',e.ROOT/'hourly-factors.parquet',
        e.previous.ROOT/'pool_dynamic_engine.py',e.previous.seed.ROOT/'dynamic_engine.py',
        e.old.ROOT/'data-manifest.json',e.old.prior.OLD/'pool-daily.parquet']
    sources.extend(sorted((e.ROOT/'signals').glob('*.json.gz')))
    e.base.dump(e.ROOT/'preflight.json',dict(passed=True,checks=checks))
    e.base.dump(e.ROOT/'frozen.json',dict(created_utc=pd.Timestamp.now(tz='UTC').isoformat(),
        files={str(p.relative_to(e.ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}))
    print('Preflight passed; code, rules and data frozen before candidate outcomes',flush=True)


if __name__=='__main__':main()
