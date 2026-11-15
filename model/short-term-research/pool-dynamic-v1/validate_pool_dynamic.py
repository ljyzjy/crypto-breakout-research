import json,hashlib
import pandas as pd
import pool_dynamic_engine as e
def main():
    frozen=e.base.read(e.ROOT/'frozen.json')
    for path,sha in frozen['files'].items():assert hashlib.sha256((e.ROOT.parent/path).read_bytes()).hexdigest()==sha
    rows=e.base.read(e.ROOT/'metrics.json');assert len(rows)==80;count=0;adds=0
    for row in rows:
        r=e.base.read(e.ROOT/'results'/(row['id']+'.json.gz'));count+=r['trade_count']
        if r['valid_for_comparison']:
            assert r['ledger_error']<1e-7 and r['cash_min']>=-1e-7
            assert abs(r['gross_pnl']-r['fees']-r['slippage_cost']-r['funding_cost']-(r['final_equity']-1000))<1e-7
        else:assert all(r[k] is None for k in ('final_equity','return_pct','annualized_return_pct','max_drawdown'))
        held={};audit={(a['ts'],a['symbol']):a for a in r['leverage_audit']};trace={int(pd.Timestamp(a['date'],tz='UTC').timestamp()):a for a in r['selection_trace']}
        for o in r['orders']:
            if o['information_ts'] is not None:assert o['information_ts']<=o['ts']
            s=o['symbol'];layer=o['layer']
            if o['action']=='open':
                if layer=='core':
                    assert s not in held;held[s]={'core':o['qty']};assert len(held)<=2
                    if r['selector']!='btc_eth':assert s in trace[o['information_ts']]['selected'] and o['side']==1
                else:
                    assert layer not in held[s] and abs(o['qty']-.5*held[s]['core'])<1e-9;held[s][layer]=o['qty'];assert len(held[s])<=9
                    assert o['core_age_hours']>=24 and o['core_net_unrealized']>0 and o['pre_account_dd']<5 and o['stop_risk_pct']<=2+1e-8
                    a=audit[(o['ts'],s)];level,_=e.regime(a['features'],o['side'],'tiered');assert int(layer[-1])<=round((level-1)*2);adds+=1
            else:
                assert layer in held[s];held[s].pop(layer)
                if layer=='core':assert not held[s];held.pop(s)
            assert o['cash']>=-1e-7
        for x in r['funding_events']:
            assert x['payment']*x['side']*x['rate']>=0
            if x['new_boundary_entry']:assert x['payment']>0
    prefix=[]
    for end in ('2025-06-30','2026-03-31'):
        for mode in e.NAMES:
            full=e.cached_run('2025-01-01','2026-04-26',mode);r=e.simulate('2025-01-01',end,mode);cut=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)).timestamp())
            filt=lambda a:[o for o in a if o['ts']<=cut and o['reason'] not in ('window_end','core_window_end')]
            assert filt(full['orders'])==filt(r['orders']),(mode,end)
            assert full['selection_trace'][:len(r['selection_trace'])]==r['selection_trace']
            prefix.append(dict(mode=mode,end=end,orders=len(filt(r['orders'])),passed=True));print('Order/heldselection prefix',mode,end,'passed',flush=True)
    e.base.dump(e.ROOT/'validation.json',dict(passed=True,scenarios=80,scenario_trades=count,audited_boost_fills=adds,frozen_hashes_verified=True,prefix=prefix,preflight=e.base.read(e.ROOT/'preflight.json'),limits=['Incompletefullperiod dueknownmissingmarkarchive','Prefixcut determinedfromdataavailabilitybeforeoutcomes','Noindependentholdout','Allpool remainslongonly,BTCETHreference islongshort']))
    print(json.dumps({'passed':True,'scenario_trades':count,'audited_boost_fills':adds}))
if __name__=='__main__':main()
