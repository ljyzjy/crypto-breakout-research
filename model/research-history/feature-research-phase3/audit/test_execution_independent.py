"""Finite execution oracles, separately authored from account synthetic tests."""
from pathlib import Path
import sys, json, hashlib
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'account'))
from engine import simulate
M=60_000
LO=1735689600000
SC={'id':'independent_synthetic','fee':.0005,'slippage':.0005,'delay_minutes':0}

class Guard:
    def eligible(self,*args):return True
    def correlation(self,*args):return 0.

class Market:
    def __init__(self,changed=None,settlements=None,bad_funding_at=None):
        self.changed=changed or {}; self.funding=settlements or {}; self.bad_funding_at=bad_funding_at
    def change_month(self,ts):pass
    def bar(self,c,ts,mark=False):
        return np.array(self.changed.get((ts,mark),[100.,100.1,99.9,100.,1_000_000.,100_000_000.]))
    def funding_ok(self,c,ts):return ts!=self.bad_funding_at

def signal(side=1,ts=LO+M):
    return dict(ts=ts,symbol='AUDIT',contract='AUDIT',side=side,signal_close=100.,
        stop_price=99.5 if side==1 else 100.5,atr=1.,score=float(side),rank=1,
        pool_rank=1,rvol=2.,break_ts=ts-7*M,touch_ts=ts-M,risk_multiplier=1.)

def run(market,side=1,scenario=None):
    return simulate(scenario or SC,pd.DataFrame([signal(side)]),'2025-01-01','2025-01-01',
        market=market,guard=Guard(),save=False,run_id='independent_synthetic')

def assert_ledger(summary,trades,funding):
    pnl=0.
    for t in trades:
        s=1 if t['side']=='long' else -1; q=t['qty']
        np.testing.assert_allclose(t['entry'],t['raw_entry']*(1+s*SC['slippage']))
        np.testing.assert_allclose(t['exit'],t['raw_exit']*(1-s*SC['slippage']))
        fees=q*(t['entry']+t['exit'])*SC['fee']
        f=sum(x['actual_charge'] for x in funding if x['symbol']==t['symbol'] and x['entry_ts']==t['entry_ts'])
        expected=s*q*(t['exit']-t['entry'])-fees-f
        np.testing.assert_allclose(t['fees'],fees,atol=1e-10)
        np.testing.assert_allclose(t['net'],expected,atol=1e-10)
        pnl+=expected
    np.testing.assert_allclose(summary['final_equity'],1000+pnl,atol=1e-8)

def stop_priority_and_gap():
    for side in [-1,1]:
        market=Market({(LO+M,False):[100.,102.,98.,100.,1e6,1e8]})
        summary,curve,trades,entries,funding=run(market,side)
        assert trades[0]['reason']=='stop' and trades[0]['ambiguous']
        assert_ledger(summary,trades,funding)
        assert len(curve)==1440
    market=Market({(LO+2*M,False):[97.,97.1,96.9,97.,1e6,1e8]})
    summary,_,trades,_,funding=run(market)
    assert trades[0]['raw_exit']==97 and trades[0]['reason']=='gap_stop'
    assert_ledger(summary,trades,funding)

def exit_funding_coverage_required():
    market=Market({(LO+2*M,False):[97.,97.1,96.9,97.,1e6,1e8]},bad_funding_at=LO+2*M)
    summary,*_=run(market)
    assert not summary['valid_for_comparison'], 'Opening exit bypassed funding coverage audit'
    assert any('funding' in x for x in summary['issues'])

def stress_includes_samebar_funding():
    changed={(LO+M,False):[100.,100.1,99.,100.,1e6,1e8],
             (LO+M,True):[100.,100.1,99.,100.,1e6,1e8]}
    events={'AUDIT':{LO+M:[(LO+M+17,.02)]}}
    summary,_,trades,_,funding=run(Market(changed,events))
    assert len(trades)==1 and len(funding)==1
    t=trades[0]
    expected_stress_equity=1000-t['entry_fee']+t['qty']*(99-t['entry'])-funding[0]['actual_charge']
    expected_dd=(1-expected_stress_equity/1000)*100
    assert summary['intrabar_stress_dd']>=expected_dd-1e-10, (summary['intrabar_stress_dd'],expected_dd)
    assert_ledger(summary,trades,funding)

def funding_sign_and_boundary():
    for side in [-1,1]:
        events={'AUDIT':{LO+3*M:[(LO+3*M+11,.001)]}}
        summary,_,trades,_,funding=run(Market(settlements=events),side)
        f=funding[0]
        np.testing.assert_allclose(f['actual_charge'],side*f['qty']*f['mark_open']*.001)
        assert f['settlement_ts']==LO+3*M+11 and not f['boundary_ambiguous']
        assert_ledger(summary,trades,funding)
    summary,_,trades,_,funding=run(Market(settlements={'AUDIT':{LO+M:[(LO+M,-.001)]}}))
    assert funding[0]['actual_charge']==0 and funding[0]['signed_charge']<0
    assert_ledger(summary,trades,funding)

def future_perturbation():
    base=run(Market())
    mutation={(LO+10*M,False):[110.,120.,90.,100.,1e6,1e8],
              (LO+10*M,True):[110.,120.,90.,100.,1e6,1e8]}
    other=run(Market(mutation))
    pd.testing.assert_frame_equal(base[1].loc[base[1].ts<=LO+10*M],other[1].loc[other[1].ts<=LO+10*M])
    assert base[3][0]==other[3][0]

if __name__=='__main__':
    checks=[]
    for fn in [stop_priority_and_gap,exit_funding_coverage_required,stress_includes_samebar_funding,
               funding_sign_and_boundary,future_perturbation]:
        try:fn(); checks.append({'name':fn.__name__,'passed':True})
        except Exception as exc:checks.append({'name':fn.__name__,'passed':False,'error':str(exc)})
    result={'created_utc':datetime.now(timezone.utc).isoformat(),'checks':checks,
        'all_passed':all(x['passed'] for x in checks),
        'engine_sha256':hashlib.sha256((ROOT.parent/'account/engine.py').read_bytes()).hexdigest(),
        'real_strategy_outcomes_computed':False}
    (ROOT/'independent_execution.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['all_passed']:
        initial=ROOT/'independent_execution_initial_failure.json'
        if not initial.exists():initial.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
