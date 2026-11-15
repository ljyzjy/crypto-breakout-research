import json,hashlib
import pandas as pd
import dynamic_engine as e

def main():
    f=e.base.read(e.ROOT/'frozen.json')
    for name,sha in f['files'].items():assert hashlib.sha256((e.ROOT/name).read_bytes()).hexdigest()==sha
    assert hashlib.sha256((e.ROOT/'protocol.json').read_bytes()).hexdigest()==f['protocol']
    assert hashlib.sha256((e.prior.old.ROOT/'data-manifest.json').read_bytes()).hexdigest()==f['perp_manifest']
    assert hashlib.sha256((e.prior.old.prior.old.ROOT/'pool-data-manifest.json').read_bytes()).hexdigest()==f['daily_manifest']
    rows=e.base.read(e.ROOT/'metrics.json');assert len(rows)==30;count=0;adds=0
    for row in rows:
        r=e.base.read(e.ROOT/'results'/(row['id']+'.json.gz'));count+=r['trade_count']
        if r['valid_for_comparison']:
            assert r['ledger_error']<1e-7 and r['cash_min']>=-1e-7
            assert abs(r['gross_pnl']-r['fees']-r['slippage_cost']-r['funding_cost']-(r['final_equity']-1000))<1e-7
        else:assert all(r[k] is None for k in ('final_equity','return_pct','annualized_return_pct','max_drawdown'))
        held={};audit={(a['ts'],a['symbol']):a for a in r['leverage_audit']}
        for o in r['orders']:
            if o['information_ts'] is not None:assert o['information_ts']<=o['ts']
            s=o['symbol'];layer=o['layer']
            if o['action']=='open':
                if layer=='core':assert s not in held;held[s]={'core':o['qty']};assert len(held)<=2
                else:
                    assert layer not in held[s] and abs(o['qty']-.5*held[s]['core'])<1e-9;held[s][layer]=o['qty'];assert len(held[s])<=9
                    assert o['core_age_hours']>=24 and o['core_net_unrealized']>0 and o['pre_account_dd']<5 and o['stop_risk_pct']<=2+1e-8
                    a=audit[(o['ts'],s)];level,_=e.regime(a['features'],o['side'],r['mode']);assert int(layer[-1])<=round((level-1)*2);adds+=1
            else:
                assert layer in held[s];held[s].pop(layer)
                if layer=='core':assert not held[s];held.pop(s)
            assert o['cash']>=-1e-7
        for x in r['funding_events']:
            assert x['payment']*x['side']*x['rate']>=0
            if x['new_boundary_entry']:assert x['payment']>0
    prefix=[]
    for mode in ('vol_only','tiered'):
        full=e.cached_run('2025-01-01','2026-10-31',mode)
        for end in ('2025-06-30','2026-06-30'):
            r=e.simulate('2025-01-01',end,mode);cut=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp())
            filt=lambda a:[o for o in a if o['ts']<=cut and o['reason'] not in ('window_end','core_window_end')]
            assert filt(full['orders'])==filt(r['orders']),(mode,end)
            prefix.append(dict(mode=mode,end=end,orders=len(filt(r['orders'])),passed=True));print('prefix',mode,end,'passed',flush=True)
    e.base.dump(e.ROOT/'validation.json',dict(passed=True,scenarios=30,scenario_trades=count,audited_boost_fills=adds,frozen_hashes_verified=True,prefix=prefix,preflight=e.base.read(e.ROOT/'preflight.json'),limits=['Knownhistory,noindependentholdout','5x isceilingnotmandatoryallocation','7percentcollateralstressnotexchangeexactMMR','Historic15percentDDnotfutureguarantee']))
    print(json.dumps({'passed':True,'scenario_trades':count,'audited_boost_fills':adds}))
if __name__=='__main__':main()
