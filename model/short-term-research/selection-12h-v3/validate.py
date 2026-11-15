import hashlib,gc
import cadence_engine as e
import importlib.util
spec=importlib.util.spec_from_file_location('selection_v2_validation',e.previous.ROOT/'validate_results.py')
parent_validation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent_validation)
paper_check=parent_validation.paper_check

def main():
    checks=e.base.read(e.ROOT/'preflight.json')['checks']
    for path,sha in e.base.read(e.ROOT/'frozen.json')['files'].items():
        assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha,path
    rows=e.base.read(e.ROOT/'metrics.json');assert len(rows)==60
    assert len({(r['mode'],r['scenario']) for r in rows})==60
    for item in rows:
        r=e.base.read(e.ROOT/'results'/(item['id']+'.json.gz'))
        if r['valid_for_comparison']:
            net=sum(t['pnl'] for t in r['trades'])
            assert abs(1000+net-r['final_equity'])<1e-7
            assert abs(r['gross_pnl']-r['fees']-r['slippage_cost']-r['funding_cost']-net)<1e-7
            assert abs(sum(t['payment'] for t in r['funding_events'])-r['funding_cost'])<1e-7
            assert abs(r['curve'][-1][1]-r['final_equity'])<1e-7
        else:assert r['return_pct'] is None and r['annualized_return_pct'] is None and r['max_drawdown'] is None
        for o in r['orders']:
            assert o['information_ts'] is None or o['information_ts']<=o['ts']
            if o['action']=='open' or o['reason']=='signal_exit':assert (o['ts']-r['delay_minutes']*60)%43200==0
            if o['reason']=='leverage_add':
                assert (o['ts']-r['delay_minutes']*60)%86400==0
                assert o['core_age_hours']>=24 and o['core_net_unrealized']>0 and o['pre_account_dd']<5 and o['stop_risk_pct']<=2+1e-9
        assert all(a['actual']<=5 for a in r['leverage_audit'])
        assert all(e.pd.Timestamp(row['date']).hour in (0,12) for row in r['selection_trace'])
    checks.append('60条新场景的资金账本、手续费/滑点/资金费与净值全部对齐；所有换仓订单仅在12小时边界或预设延迟后执行')
    for mode in ('combined_12h__fixed1','combined_12h__tiered'):
        small=e.simulate('2025-01-01','2025-06-30',mode)
        full=e.cached_run('2025-01-01','2025-12-31',mode)
        cutoff=int(e.pd.Timestamp('2025-07-01',tz='UTC').timestamp())
        assert [o for o in small['orders'] if o['ts']<cutoff]==[o for o in full['orders'] if o['ts']<cutoff]
        del small,full;e.prepare.cache_clear();e.previous.prepare.cache_clear();gc.collect()
    checks.append('12小时主要候选1×与动态5×实际订单通过未来截断前缀检查')
    paper=paper_check();checks.append('原模拟引擎进程、启动时间与受保护配置/策略文件保持不变')
    e.base.dump(e.ROOT/'validation.json',dict(passed=True,checks=checks,paths=60,valid_paths=sum(r['valid_for_comparison'] for r in rows),paper=paper,
        parent_validation=e.base.read(e.previous.ROOT/'validation.json')['passed']))
    print('All12h validation passed; paper engine',paper['pid'],flush=True)

if __name__=='__main__':main()
