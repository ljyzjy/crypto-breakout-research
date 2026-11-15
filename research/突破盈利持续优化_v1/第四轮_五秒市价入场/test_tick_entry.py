"""Check 5s entry timestamps, no pre-entry bar extrema, and funding order."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase3\account')
sp=importlib.util.spec_from_file_location('tick_test',HERE/'tick_entry_engine.py')
eng=importlib.util.module_from_spec(sp);sys.modules[sp.name]=eng;sp.loader.exec_module(eng)
M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000);decision=base+M
class Market:
    def __init__(self):self.funding={'BTCUSDT':{decision:[(decision,.01)]}}
    def change_month(self,t):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):
        if t==decision and not mark:return np.array([100.6,103.,98.8,100.6,100.,1e6])
        return np.array([100.6,100.8,100.3,100.6,100.,1e6])
class Guard:
    def eligible(self,s,side,t):return True
    def correlation(self,*args):return 0.
row={'ts':decision,'decision_ts':decision,'feature_known_ts':decision,'observation_id':'tick_test',
     'symbol':'BTCUSDT','contract':'BTCUSDT','side':1,'signal_close':100.6,'atr':2.,
     'stop_price':99.5,'level':100.5,'break_ts':base,'touch_ts':base,'score':1.,'rank':1,
     'rvol':2.,'liquidity_rank':1,'risk_multiplier':1.,'tick_status':'verified',
     'entry_exec_ts':decision+5001,'raw_entry_5s':100.6,'suffix_high':100.8,
     'suffix_low':100.3,'suffix_close':100.6}
def run(r):
    scenario={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':1.,'leverage':10}
    return eng.simulate(scenario,pd.DataFrame([r]),'2026-05-01','2026-05-01',market=Market(),guard=Guard(),save=False)
sm,_,trades,entries,fund=run(row)
assert sm['valid_for_comparison'] and len(trades)==1
t=trades[0];assert t['entry_ts']==decision+5001 and t['entry_bar_ts']==decision
assert np.isclose(t['entry'],t['raw_entry']*1.0005)
assert t['reason']=='time60' and t['funding']==0 and not fund
both={**row,'suffix_high':103.,'suffix_low':98.8}
sm2,_,trades2,_,_=run(both)
assert sm2['valid_for_comparison'] and trades2[0]['reason']=='stop' and trades2[0]['ambiguous']
missing={**row,'tick_status':'no_trade_after_5s'}
sm3,_,trades3,_,_=run(missing)
assert sm3['valid_for_comparison'] and not trades3 and sm3['rejection_counts']['tick_unavailable']==1
early={**row,'entry_exec_ts':decision+3000}
sm4,_,_,_,_=run(early)
assert not sm4['valid_for_comparison'] and 'invalid_tick_execution_time' in sm4['issues']
short={**row,'side':-1,'stop_price':101.7,'level':100.7,'suffix_high':102.,'suffix_low':99.}
sm5,_,trades5,_,_=run(short)
assert sm5['valid_for_comparison'] and trades5[0]['reason']=='stop' and trades5[0]['ambiguous']
assert np.isclose(trades5[0]['entry'],trades5[0]['raw_entry']*.9995)
report={'entry_at_least_five_seconds':True,'adverse_entry_slippage':True,'pre_entry_extrema_excluded':True,
        'prior_funding_not_charged':True,'same_minute_stop_priority':True,'short_stop_priority':True,'missing_tick_rejected':True,
        'post_entry_exit_resolution':'one minute; stops first if both hit'}
(HERE/'五秒入场合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('FIVE_SECOND_ENGINE_VALIDATED',json.dumps(report),flush=True)
