"""Synthetic accounting checks. No historical signals/outcomes are consumed."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from engine import simulate, MINUTE

ROOT=Path(__file__).resolve().parent
LO=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
MAIN={'id':'synthetic','fee':.0005,'slippage':.0005,'delay_minutes':0}


class Guard:
    def eligible(self,*args):return True
    def correlation(self,*args):return 0.


class Market:
    def __init__(self,changes=None,funding=None,missing=None,funding_missing=None):
        self.changes=changes or {};self.funding=funding or {};self.missing=missing
        self.funding_missing=funding_missing
    def change_month(self,ts):pass
    def bar(self,c,ts,mark=False):
        if self.missing is not None and ts==self.missing:return None
        return np.array(self.changes.get((ts,mark),[100.,100.1,99.9,100.,1e6,1e8]),float)
    def funding_ok(self,c,ts):return ts!=self.funding_missing


def signal(side=1,ts=LO+MINUTE,symbol='TESTUSDT'):
    return {'ts':ts,'symbol':symbol,'contract':symbol,'side':side,'signal_close':100.,
            'stop_price':99.5 if side==1 else 100.5,'atr':1.,'score':side,'rank':1,
            'rvol':2.,'break_ts':ts-6*MINUTE,'touch_ts':ts-MINUTE,'risk_multiplier':1.}


def run(signals,market,scenario=None):
    return simulate(scenario or MAIN,pd.DataFrame(signals),'2025-01-01','2025-01-01',
                    market=market,guard=Guard(),save=False,run_id='synthetic')


def main():
    tests=[]
    # Both levels touched: the original engine's conservative stop priority.
    s=signal();m=Market({(LO+MINUTE,False):[100.,102.,99.,100.,1e6,1e8]})
    summary,curve,trades,entries,funding=run([s],m)
    t=trades[0]
    assert t['reason']=='stop' and t['ambiguous'] and t['entry_ts']==s['ts']
    assert t['entry']==100*(1+.0005) and t['exit']==99.5*(1-.0005)
    assert abs(t['net']-(t['gross']-t['fees']-t['slippage']-t['funding']))<1e-9
    assert abs(summary['ledger_error'])<1e-8 and len(curve)==1440
    tests.append('samebar_stop_first_and_fee_slip_ledger')
    # Overnight gap through stop uses open, not the stop level.
    m=Market({(LO+2*MINUTE,False):[98.,98.1,97.9,98.,1e6,1e8]})
    summary,curve,trades,*_=run([s],m)
    assert trades[0]['reason']=='gap_stop' and trades[0]['raw_exit']==98.
    tests.append('gap_stop_at_open')
    # Same magnitude funding credits short and debits long when timing unambiguous.
    for side in (1,-1):
        ft=LO+3*MINUTE+3
        m=Market(funding={'TESTUSDT':{LO+3*MINUTE:[(ft,.001)]}})
        summary,curve,trades,entries,funding=run([signal(side)],m)
        assert len(funding)==1 and funding[0]['settlement_ts']==ft
        assert np.sign(funding[0]['actual_charge'])==side and not funding[0]['boundary_ambiguous']
        assert abs(summary['ledger_error'])<1e-8
    tests.append('signed_funding_milliseconds_and_ledger')
    # At entry boundary, ambiguous receipts are suppressed rather than credited.
    m=Market(funding={'TESTUSDT':{LO+MINUTE:[(LO+MINUTE,-.001)]}})
    *_,funding=run([s],m)
    assert funding[0]['actual_charge']==0 and funding[0]['signed_charge']<0
    tests.append('entry_boundary_funding_debit_only')
    # Missing future held data invalidates path, never silently drops the trade.
    summary,curve,*_=run([s],Market(missing=LO+3*MINUTE))
    assert not summary['valid_for_comparison'] and summary['issues'][0].startswith('held_missing_bar:')
    assert len(curve)<1440
    tests.append('held_missing_invalidates_path')
    # One minute stress delay is an additional minute after already-lagged signal ts.
    summary,curve,trades,*_=run([s],Market(),dict(MAIN,delay_minutes=1))
    assert trades[0]['entry_ts']==s['ts']+MINUTE
    tests.append('additional_minute_execution_delay')
    # A risk modifier can only reduce risk; no hidden leverage.
    a=run([s],Market())[3][0]
    b=run([dict(s,risk_multiplier=.5)],Market())[3][0]
    assert b['planned_loss']<=a['planned_loss']*.5000001
    assert b['gross_after']<=b['known_equity'] and b['notional']<=.5*b['known_equity']
    tests.append('risk_half_and_1x_cap')
    m=Market({(LO+2*MINUTE,False):[98.,98.1,97.9,98.,1e6,1e8]},funding_missing=LO+2*MINUTE)
    summary,curve,*_=run([s],m)
    assert not summary['valid_for_comparison'] and summary['issues'][0].startswith('held_funding_coverage_missing:')
    tests.append('open_gap_exit_cannot_skip_funding_coverage')
    with_funding=run([s],Market(funding={'TESTUSDT':{LO+MINUTE:[(LO+MINUTE,.02)]}}))[0]
    without=run([s],Market())[0]
    assert with_funding['intrabar_stress_dd']>without['intrabar_stress_dd']
    tests.append('intrabar_stress_includes_same_minute_funding')
    m=Market({(LO+2*MINUTE,False):[70.,70.1,69.9,70.,1e6,1e8]})
    summary,curve,trades,*_=run([s,signal(ts=LO+180*MINUTE)],m)
    assert summary['permanent_pause_ts']==LO+3*MINUTE
    assert len(trades)==1 and summary['halted_days']>0 and len(curve)==1440
    assert summary['rejection_counts']['account_pause']==1
    tests.append('8percent_halt_retains_calendar_and_prevents_restart')
    result={'passed':len(tests),'tests':tests,'historical_strategy_outcomes_computed':False}
    (ROOT/'synthetic_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
