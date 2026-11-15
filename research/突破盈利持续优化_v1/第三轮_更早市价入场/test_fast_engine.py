"""Verify timestamp causality and adverse entry slippage for fast scenarios."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase3\account')
spec=importlib.util.spec_from_file_location('fast_test_engine',HERE/'fast_engine.py')
engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
class Market:
    funding={}
    def change_month(self,ts):pass
    def funding_ok(self,c,ts):return True
    def bar(self,c,ts,mark=False):return np.array([100.6,101.,100.2,100.6,100.,1e6],float)
class Guard:
    def eligible(self,s,side,ts):return True
    def correlation(self,*args):return 0.
row={'ts':base+M,'decision_ts':base+M,'feature_known_ts':base+M,'observation_id':'fast_test',
     'symbol':'BTCUSDT','contract':'BTCUSDT','side':1,'signal_close':100.6,'atr':2.,
     'stop_price':99.5,'level':100.5,'break_ts':base,'touch_ts':base,'score':1.,'rank':1,
     'rvol':2.,'liquidity_rank':1,'risk_multiplier':1.}
def run(row,delay):
    sc={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':delay,'target_r':1.,'leverage':10}
    return engine.simulate(sc,pd.DataFrame([row]),'2026-05-01','2026-05-01',market=Market(),guard=Guard(),save=False)
sm,_,trades,_,_=run(row,0)
assert sm['valid_for_comparison'] and len(trades)==1 and trades[0]['entry_ts']==row['decision_ts']
assert np.isclose(trades[0]['entry'],trades[0]['raw_entry']*1.0005)
sm2,_,trades2,_,_=run(row,1)
assert sm2['valid_for_comparison'] and trades2[0]['entry_ts']==row['decision_ts']+M
bad={**row,'ts':base}
sm3,_,_,_,_=run(bad,0)
assert not sm3['valid_for_comparison'] and 'noncausal_signal_arrival' in sm3['issues']
report={'decision_open_entry_allowed':True,'entry_slippage_applied':True,'extra_delay_one_minute':True,
        'entry_before_signal_rejected':True,'limit':'decision-open price is an optimistic execution assumption, not a measured fill'}
(HERE/'提前入场合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('FAST_ENTRY_SYNTHETICS_PASS',json.dumps(report),flush=True)
