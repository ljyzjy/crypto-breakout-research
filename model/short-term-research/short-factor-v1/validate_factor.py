import hashlib,json
import pandas as pd
import factor_engine as e

def main():
    f=e.base.read(e.ROOT/'frozen.json')
    for name,sha in f['files'].items():assert hashlib.sha256((e.ROOT/name).read_bytes()).hexdigest()==sha
    assert hashlib.sha256((e.ROOT/'protocol.json').read_bytes()).hexdigest()==f['protocol']
    assert hashlib.sha256((e.old.ROOT/'data-manifest.json').read_bytes()).hexdigest()==f['data_manifest']
    rows=e.base.read(e.ROOT/'metrics.json');assert len(rows)==240
    count=0
    for row in rows:
        r=e.base.read(e.ROOT/'results'/(row['id']+'.json.gz'))
        if r['valid_for_comparison']:
            assert r['ledger_error']<1e-7 and r['cash_min']>=-1e-7
            assert abs(1000+sum(t['pnl'] for t in r['trades'])-r['final_equity'])<1e-7
            assert abs(r['gross_pnl']-r['fees']-r['slippage_cost']-r['funding_cost']-(r['final_equity']-1000))<1e-7
        else:assert all(r[k] is None for k in ('final_equity','return_pct','annualized_return_pct','max_drawdown'))
        count+=r['trade_count']
        if r['mode']=='long_control':continue
        held={}
        for o in r['orders']:
            if o['information_ts'] is not None:assert o['information_ts']<=o['ts']
            if o['action']=='open':
                assert o['symbol'] not in held;held[o['symbol']]=o['side'];assert len(held)<=2
            else:assert held.pop(o['symbol'])==-o['side']
            assert o['cash']>=-1e-7
        for t in r['trades']:
            side=1 if t['direction']=='long' else -1
            assert side*(t['entry_price']-t['entry_reference'])>=0 and side*(t['exit_price']-t['exit_reference'])<=0
        for x in r['funding_events']:
            assert x['payment']*x['direction']*x['rate']>=0
            if x['new_boundary_entry']:assert x['payment']>0
    prefix=[]
    for mode in ('momentum_ls','sweep_ls','sweep_trend'):
        full=e.cached_run('2025-01-01','2026-10-31',mode)
        for end in ('2025-06-30','2026-06-30'):
            r=e.simulate('2025-01-01',end,mode);cut=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp())
            left=[o for o in full['orders'] if o['ts']<=cut and o['reason']!='window_end'];right=[o for o in r['orders'] if o['reason']!='window_end']
            assert left==right,(mode,end,len(left),len(right))
            prefix.append(dict(mode=mode,end=end,orders=len(right),passed=True));print('prefix',mode,end,flush=True)
    e.base.dump(e.ROOT/'validation.json',dict(passed=True,scenarios=240,scenario_trades=count,source_hashes_verified=True,prefix=prefix,preflight=e.base.read(e.ROOT/'preflight.json'),limits=['Known history,not independent holdout','OHLC proxy,not original strategy replication','BTCETH only','7percentcollateral assumption;15percentexecutionclose historical gate']))
    print(json.dumps({'passed':True,'scenario_trades':count,'prefix_checks':len(prefix)}))
if __name__=='__main__':main()
