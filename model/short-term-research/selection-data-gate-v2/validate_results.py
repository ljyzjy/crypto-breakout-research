"""Ledger, causal-prefix and fixed descriptive uncertainty checks; no parameter search."""
from types import FunctionType,SimpleNamespace
from pathlib import Path
import hashlib
import gc
import numpy as np
import pandas as pd
import psutil
import availability_engine as e
from selection_execution import simulate_path


def paper_check():
    before=e.base.read(e.ROOT/'paper-before.json');kit=e.ROOT.parent.parent
    for path,sha in before['hashes'].items():
        assert hashlib.sha256((kit/path).read_bytes()).hexdigest()==sha,path
    ident=before['processes']['engine'];p=psutil.Process(ident['pid'])
    assert p.is_running() and abs(p.create_time()-ident['created'])<.01
    assert 'DailyMomentum' in p.cmdline()
    return dict(pid=p.pid,created=p.create_time(),protected_hashes_unchanged=True)


def raw_daily(mode):
    selector=mode.split('__')[0]
    z=e.prepare('2025-01-01','2025-12-31',selector)
    scope=dict(e.previous.simulate.__globals__)
    namespace=dict(vars(e.base));namespace['compress_curve']=lambda x:x
    scope.update(NAMES=e.NAMES,hourly_rotation=selector.endswith('_hourly'),base=SimpleNamespace(**namespace))
    fn=FunctionType(simulate_path.__code__,scope,argdefs=simulate_path.__defaults__)
    r=fn('2025-01-01','2025-12-31',mode,.0005,0,z,e.leverage_features())
    cache=e.cached_run('2025-01-01','2025-12-31',mode,.0005)
    assert r['final_equity']==cache['final_equity'] and r['trades']==cache['trades']
    curve=pd.DataFrame(r['curve'],columns=['ts','equity','dd','exposure'])
    daily=curve.loc[curve.ts.mod(86400).eq(0)].set_index('ts').equity
    assert len(daily)==366
    return daily.pct_change().dropna()


def main():
    checks=list(e.base.read(e.ROOT/'preflight.json')['checks'])
    for path,sha in e.base.read(e.ROOT/'frozen.json')['files'].items():
        assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha,path
    rows=e.base.read(e.ROOT/'metrics.json')
    assert len(rows)==84 and len({(r['mode'],r['scenario']) for r in rows})==84
    references=e.base.read(e.ROOT/'official-metrics.json')
    assert len(references)==84 and len({(r['mode'],r['scenario']) for r in references})==84
    assert hashlib.sha256((e.ROOT/'official-protocol.json').read_bytes()).hexdigest()==e.base.read(e.ROOT/'official-frozen.json')['protocol_sha256']
    rows=rows+references
    maximum_multiplier=1;maximum_ledger_error=0.;valid=0
    for row in rows:
        r=e.base.read(e.ROOT/'results'/(row['id']+'.json.gz'))
        if r['valid_for_comparison']:
            valid+=1
            net=sum(t['pnl'] for t in r['trades'])
            assert abs(r['final_equity']-1000-net)<1e-7
            assert abs(r['gross_pnl']-r['fees']-r['slippage_cost']-r['funding_cost']-net)<1e-7
            assert abs(sum(f['payment'] for f in r['funding_events'])-r['funding_cost'])<1e-7
            assert abs(r['curve'][-1][1]-r['final_equity'])<1e-7
            assert r['cash_min']>=-1e-7
            maximum_ledger_error=max(maximum_ledger_error,abs(r['final_equity']-1000-net))
        else:
            assert r['data_issues'] and r['annualized_return_pct'] is None and r['return_pct'] is None and r['max_drawdown'] is None
        for o in r['orders']:
            assert o['information_ts'] is None or o['information_ts']<=o['ts']
            if o['action']=='open':
                assert (o['ts']-r['delay_minutes']*60)%3600==0
            if o['reason']=='leverage_add':
                assert (o['ts']-r['delay_minutes']*60)%86400==0
                assert o['core_age_hours']>=24 and o['core_net_unrealized']>0 and o['pre_account_dd']<5
                assert o['stop_risk_pct']<=2+1e-9
        for a in r['leverage_audit']:
            assert a['actual']<=5
            maximum_multiplier=max(maximum_multiplier,a['actual'])
        if r['start']=='2025-01-01' and r['end']=='2025-12-31' and r['fee']==.001:
            old=e.base.read(e.V1/'results'/(row['id']+'.json.gz'))
            for key in ('return_pct','fees','slippage_cost','funding_cost','max_drawdown'):
                assert abs(r[key]-old[key])<1e-8,(r['mode'],key)
    checks.append('旧费率84场景及官方标准费率84场景的账本、手续费/滑点/资金费恒等式、期末净值及缺失抑制指标全部通过')
    checks.append('所有加杠杆订单核验：每日决策、底仓满24小时且净浮盈、加仓前回撤小于5%、计划止损风险不超过2%、数量倍数不超过5')
    checks.append('2025年全部14版本与修订前经济结果完全相同，缺失发生前没有提前排除币种')
    print('168 scenario records: ledgers and leverage constraints passed',flush=True)
    for mode in ('combined_hourly__fixed1','liquidity_hourly__fixed1'):
        small=e.simulate('2025-01-01','2025-06-30',mode,.0005)
        full=e.cached_run('2025-01-01','2025-12-31',mode,.0005)
        cutoff=int(pd.Timestamp('2025-07-01',tz='UTC').timestamp())
        expected=[o for o in full['orders'] if o['ts']<cutoff]
        actual=[o for o in small['orders'] if o['ts']<cutoff and o['reason']!='window_end']
        assert actual==expected,(mode,len(actual),len(expected))
        print('Actual order prefix passed',mode,flush=True)
        del small,full;e.prepare.cache_clear();gc.collect()
    checks.append('主要候选与流动性版实际订单通过截至2025-06-30的前缀不变检查；原始小时因子的两次原数据未来截断测试已通过')
    daily={mode:raw_daily(mode) for mode in ('combined_hourly__fixed1','control_hourly__fixed1','control_weekly__fixed1')}
    pairs=[]
    for reference in ('control_hourly__fixed1','control_weekly__fixed1'):
        diff=(daily['combined_hourly__fixed1']-daily[reference]).to_numpy()
        rng=np.random.default_rng(20261113);n=len(diff);means=[]
        for _ in range(1000):
            starts=rng.integers(0,n,size=int(np.ceil(n/7)))
            ix=((starts[:,None]+np.arange(7))%n).reshape(-1)[:n]
            means.append(diff[ix].mean()*10000)
        pairs.append(dict(candidate='combined_hourly__fixed1',reference=reference,days=n,mean_daily_difference_bps=float(diff.mean()*10000),
                          ci95_daily_difference_bps=np.quantile(means,[.025,.975]).tolist()))
    bootstrap=dict(period=['2025-01-01','2025-12-31'],repeats=1000,block_days=7,seed=20261113,
        method='Paired circular moving-block resampling of exact UTC daily net returns. Diagnostic only; history seen and multiple variants tested. Not a CAGR interval, independent holdout or adjusted discovery test.',pairs=pairs)
    e.base.dump(e.ROOT/'bootstrap.json',bootstrap)
    checks.append('2025年精确日净值的7日区块配对重采样完成；未用压缩曲线插值，未当作样本外证明')
    paper=paper_check();checks.append('原DailyMomentum模拟进程、启动时间与受保护配置/策略文件哈希保持不变')
    report=dict(passed=True,checks=checks,paths=len(rows),valid_paths=valid,maximum_quantity_multiplier=maximum_multiplier,
        max_ledger_error=maximum_ledger_error,paper=paper,bootstrap=bootstrap)
    e.base.dump(e.ROOT/'validation.json',report)
    print('All validation passed',valid,'valid paths; paper PID',paper['pid'],flush=True)
    print('Bootstrap:',pairs,flush=True)


if __name__=='__main__':main()
