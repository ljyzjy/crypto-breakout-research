"""Test intraminute trigger, 5s causality, same-minute ambiguity and funding."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase3\account')
sp=importlib.util.spec_from_file_location('touch_test_engine',HERE/'touch_engine.py')
eng=importlib.util.module_from_spec(sp);sys.modules[sp.name]=eng;sp.loader.exec_module(eng)
M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
class Market:
    def __init__(self):self.funding={'BTCUSDT':{base:[(base,.01)]}}
    def change_month(self,t):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):
        if t==base and not mark:return np.array([100.6,103.,98.8,100.6,100.,1e6])
        return np.array([100.6,100.8,100.3,100.6,100.,1e6])
class Guard:
    def eligible(self,s,side,t):return True
    def correlation(self,*args):return 0.
row={'ts':base,'decision_ts':base+30_000,'feature_known_ts':base,'observation_id':'touch_test',
     'symbol':'BTCUSDT','contract':'BTCUSDT','side':1,'signal_close':100.6,'atr':2.,
     'stop_price':99.5,'level':100.5,'break_ts':base,'touch_ts':base+30_000,'score':1.,'rank':1,
     'rvol':2.,'liquidity_rank':1,'risk_multiplier':1.,'tick_status':'verified',
     'entry_exec_ts':base+35_501,'raw_entry_5s':100.6,'suffix_high':100.8,
     'suffix_low':100.3,'suffix_close':100.6}
def run(r):
    scenario={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':1.,'leverage':10}
    return eng.simulate(scenario,pd.DataFrame([r]),'2026-05-01','2026-05-01',market=Market(),guard=Guard(),save=False)
sm,_,trades,entries,funding=run(row)
assert sm['valid_for_comparison'] and len(trades)==1
t=trades[0];assert t['entry_ts']==base+35_501 and t['decision_ts']==base+30_000
assert t['reason']=='time60' and t['funding']==0 and not funding
assert np.isclose(t['entry'],t['raw_entry']*1.0005)
both={**row,'suffix_high':103.,'suffix_low':98.8}
sm2,_,trades2,_,_=run(both)
assert sm2['valid_for_comparison'] and trades2[0]['reason']=='stop' and trades2[0]['ambiguous']
nextbar={**row,'ts':base+M,'decision_ts':base+58_000,'touch_ts':base+58_000,'entry_exec_ts':base+63_100}
sm3,_,trades3,_,_=run(nextbar)
assert sm3['valid_for_comparison'] and trades3[0]['entry_ts']==base+63_100
early={**row,'entry_exec_ts':base+34_999}
sm4,_,_,_,_=run(early)
assert not sm4['valid_for_comparison'] and 'invalid_tick_execution_time' in sm4['issues']
report={'intraminute_trigger':True,'five_second_delay':True,'cross_minute_entry':True,
        'pre_entry_extrema_excluded':True,'pre_entry_funding_not_charged':True,
        'same_minute_stop_priority':True,'adverse_entry_slippage':True}
(HERE/'柱内触价合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TOUCH_ENGINE_SYNTHETICS_PASS',json.dumps(report),flush=True)
