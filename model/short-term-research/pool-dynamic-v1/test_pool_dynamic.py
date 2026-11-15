import json,hashlib
from types import FunctionType,SimpleNamespace
import numpy as np
import pandas as pd
import pool_dynamic_engine as e
from test_dynamic import fixture as seed_fixture

def fixture():
    z,f=seed_fixture();z['symbols']=e.seed.SYMBOLS
    z['trace']={int(t.timestamp()):dict(date=t.strftime('%Y-%m-%d'),information_through=(t-pd.Timedelta(days=1)).strftime('%Y-%m-%d'),daily_top2=['BTCUSDT'],ranked=[{'symbol':'BTCUSDT'},{'symbol':'ETHUSDT'}]) for t in f['BTCUSDT'].index}
    return z,f

def main():
    checks=[]
    z,f=fixture();r=e.simulate('2025-01-01','2025-01-04','slow_base__tiered',fixture=z,feature_fixture=f)
    adds=[o for o in r['orders'] if o['reason']=='leverage_add'];assert len(adds)==8 and all(o['ts']==1735776000 and o['stop_risk_pct']<=2 for o in adds)
    for issue in ('missing_prior','missing_held','collateral'):
        z,f=fixture()
        if issue=='missing_prior':z['avail']['BTCUSDT'][0]=2
        elif issue=='missing_held':z['ok']['BTCUSDT'][300]=False
        else:z['mk']['BTCUSDT'][300,2]=30.
        r=e.simulate('2025-01-01','2025-01-04','slow_base__tiered',fixture=z,feature_fixture=f)
        assert not r['valid_for_comparison'] and all(r[k] is None for k in ('return_pct','annualized_return_pct','max_drawdown'))
    z,f=fixture();z['px']['BTCUSDT'][100,2]=95.;z['mk']['BTCUSDT'][100,2]=95.
    a=e.simulate('2025-01-01','2025-01-04','slow_base__fixed1',fixture=z,feature_fixture=f);b=e.simulate('2025-01-01','2025-01-04','delayed_retry__fixed1',fixture=z,feature_fixture=f)
    assert a['core_trades']>b['core_trades']==1
    z,f=fixture();offset=pd.Timedelta(days=3);z['index']=z['index']+offset
    for s in f:f[s].index=f[s].index+offset
    z['symbols']=('BTCUSDT','ETHUSDT','TESTUSDT')
    for key in ('px','mk','rates','ok','avail','mom','budgets'):z[key]['TESTUSDT']=z[key]['BTCUSDT'].copy()
    f['TESTUSDT']=f['BTCUSDT'].copy();z['trace']={}
    for i,t in enumerate(f['BTCUSDT'].index):
        order=['BTCUSDT','ETHUSDT','TESTUSDT'] if i<2 else ['ETHUSDT','TESTUSDT','BTCUSDT']
        z['trace'][int(t.timestamp())]=dict(date=t.strftime('%Y-%m-%d'),daily_top2=order[:2],ranked=[{'symbol':s} for s in order])
    a=e.simulate('2025-01-04','2025-01-07','slow_base__fixed1',fixture=z,feature_fixture=f);b=e.simulate('2025-01-04','2025-01-07','rank_buffer__fixed1',fixture=z,feature_fixture=f)
    assert 'BTCUSDT' not in a['selection_trace'][2]['selected'] and 'BTCUSDT' in b['selection_trace'][2]['selected']
    checks.append('Synthetic max5,2percentbudget,strictmissing suppression,actualholdingsrankbuffer andnextMondayretry passed')
    for end in ('2025-12-31','2026-10-31'):
        for selector in e.SELECTORS:
            a=e.simulate('2025-01-01',end,selector+'__fixed1');b=e.old.cached_run('2025-01-01',end,selector,'perp',1)
            assert a['valid_for_comparison']==b['valid_for_comparison']
            if a['valid_for_comparison']:
                for key in ('return_pct','max_drawdown','fees','slippage_cost','funding_cost','mean_exposure_pct'):assert abs(a[key]-b[key])<1e-7,(selector,key,a[key],b[key])
            else:assert a['data_issues'][0]['ts']==b['data_issues'][0]['ts'] and a['data_issues'][0]['symbol']==b['data_issues'][0]['symbol']
            assert a['core_trades']==b['trade_count'];print('Exact old1x control',selector,end,'passed',flush=True)
    checks.append('Three selectors exactly reproduce old2025 economics andoriginalfullperiod haltdate/corecount')
    raw=e.old.prior.old.daily();full=e.old.prior.slow_rankings();fullf=e.features()
    for cutoff in ('2025-06-30','2026-03-31'):
        cut=pd.Timestamp(cutoff,tz='UTC')+pd.Timedelta(days=1);short=raw.loc[raw.date<cut]
        rank=e.old.prior.old.rank_history(short);scope=dict(e.old.prior.slow_rankings.__wrapped__.__globals__);scope['old']=SimpleNamespace(daily=lambda:short,rankings=lambda:rank)
        history=FunctionType(e.old.prior.slow_rankings.__wrapped__.__code__,scope)()
        for a,b in zip(history,full):
            assert a['date']==b['date'] and a['daily_top2']==b['daily_top2']
            assert a['ranked']==b['ranked']
        syms=tuple(s for s in fullf if s in set(short.symbol));scope=dict(e.seed.features_from_daily.__globals__);scope['SYMBOLS']=syms;fn=FunctionType(e.seed.features_from_daily.__code__,scope)
        fd={}
        for s in syms:
            c=e.old.manifest()['mapping'][s];d=e.old.load_frame('perp',c,'fundingRate') if c else None
            fd[s]=d.loc[d.index<cut] if d is not None else pd.DataFrame({'last_funding_rate':pd.Series(dtype=float)},index=pd.DatetimeIndex([],tz='UTC'))
        small=fn(short,fd)
        for s in syms:pd.testing.assert_frame_equal(small[s],fullf[s].loc[small[s].index])
        print('Raw selection/features future truncation',cutoff,'passed',flush=True)
    checks.append('Fulluniverse rawselection and allavailable symbolleverage factors unchanged at2futuretruncations')
    e.base.dump(e.ROOT/'preflight.json',dict(passed=True,checks=checks))
    paths=[e.ROOT/'pool_dynamic_engine.py',e.ROOT/'protocol.json',e.seed.ROOT/'dynamic_engine.py',e.seed.ROOT/'protocol.json',e.old.ROOT/'rotation_engine.py',e.old.ROOT/'data-manifest.json',e.old.prior.OLD/'pool-data-manifest.json',e.old.prior.ROOT/'pool_engine.py',e.old.prior.OLD/'automatic_engine.py']
    e.base.dump(e.ROOT/'frozen.json',{'files':{str(p.relative_to(e.ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
    print('Preflightpassed; frozen for execution',flush=True)
if __name__=='__main__':main()
