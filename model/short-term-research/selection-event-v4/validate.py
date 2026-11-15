import hashlib,gc,importlib.util
import event_engine as e

def main():
    checks=list(e.base.read(e.ROOT/'preflight.json')['checks'])
    for path,sha in e.base.read(e.ROOT/'frozen.json')['files'].items():
        assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha,path
    rows=e.base.read(e.ROOT/'metrics.json');assert len(rows)==24
    for row in rows:
        r=e.base.read(e.ROOT/'results'/(row['id']+'.json.gz'))
        if r['valid_for_comparison']:
            net=sum(t['pnl'] for t in r['trades'])
            assert abs(r['final_equity']-1000-net)<1e-7
            assert abs(r['gross_pnl']-r['fees']-r['slippage_cost']-r['funding_cost']-net)<1e-7
            assert abs(sum(t['payment'] for t in r['funding_events'])-r['funding_cost'])<1e-7
            assert abs(r['curve'][-1][1]-r['final_equity'])<1e-7
        else:assert r['return_pct'] is None and r['max_drawdown'] is None and r['annualized_return_pct'] is None
        held={};cool={};pending=[int(e.pd.Timestamp(r['start'],tz='UTC').timestamp())+r['delay_minutes']*60]*2
        for o in r['orders']:
            assert o['information_ts'] is None or o['information_ts']<=o['ts']
            if o['layer']=='core':
                if o['action']=='open':
                    assert pending and min(pending)<=o['ts'] and o['symbol'] not in held
                    assert o['ts']>=cool.get(o['symbol'],0)
                    pending.remove(min(pending));held[o['symbol']]=o
                    assert len(held)<=2
                else:
                    assert o['reason'] in ('gap_stop','stop_loss','timing_exit','window_end')
                    held.pop(o['symbol']);cool[o['symbol']]=int(e.np.ceil((o['ts']+21600)/3600)*3600)
                    ready=o['ts'] if o['reason']=='stop_loss' else o['ts']+300
                    pending.append(ready)
                    if o['reason']=='timing_exit':assert (o['ts']-r['delay_minutes']*60)%43200==0
            if o['reason']=='leverage_add':
                assert (o['ts']-r['delay_minutes']*60)%86400==0
                assert o['core_age_hours']>=24 and o['core_net_unrealized']>0 and o['pre_account_dd']<5 and o['stop_risk_pct']<=2+1e-9
        assert all(a['actual']<=5 for a in r['leverage_audit'])
        for a in r['selection_trace']:
            assert e.pd.Timestamp(a['ranking_date']).timestamp()<=a['decision_information_ts']<=e.pd.Timestamp(a['date']).timestamp()
            assert not (set(a['replacements']) & set(a['held_before_decision']))
            ordering={p['symbol']:i for i,p in enumerate(a['ranked'])}
            ranks=[ordering[s] for s in a['replacements']]
            assert ranks==sorted(ranks)
        assert sum(len(a['replacements']) for a in r['selection_trace'])==sum(o['action']=='open' and o['layer']=='core' for o in r['orders'])
    checks.append('24条场景资金账本全部对齐；逐笔核对空位、下一可执行柱补位、冷却与独立持仓，未出现排名退出')
    for mode in ('combined_event__fixed1','combined_event__tiered'):
        small=e.simulate('2025-01-01','2025-06-30',mode)
        full=e.cached_run('2025-01-01','2025-12-31',mode)
        cut=int(e.pd.Timestamp('2025-07-01',tz='UTC').timestamp())
        assert [o for o in small['orders'] if o['ts']<cut]==[o for o in full['orders'] if o['ts']<cut]
        del small,full;e.prepare.cache_clear();gc.collect()
    checks.append('主要候选1×与动态5×实际订单通过未来截断前缀检查；日级杠杆与原风险预算约束通过')
    spec=importlib.util.spec_from_file_location('paper_verifier_event',e.parent.ROOT/'validate_results.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);paper=module.paper_check()
    checks.append('DailyMomentum模拟引擎身份与受保护配置/策略哈希保持不变')
    e.base.dump(e.ROOT/'validation.json',dict(passed=True,checks=checks,paths=24,valid_paths=sum(r['valid_for_comparison'] for r in rows),paper=paper))
    print('Event validation passed; paper',paper['pid'],flush=True)

if __name__=='__main__':main()
