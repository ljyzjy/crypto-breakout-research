"""Check 4h timing, overnight carry, and historic funding settlement."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase3\account')
sp=importlib.util.spec_from_file_location('extended_test_engine',HERE/'extended_engine.py')
eng=importlib.util.module_from_spec(sp);sys.modules[sp.name]=eng;sp.loader.exec_module(eng)
M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000);bar=base+13*60*M+50*M
class Market:
    def __init__(self):self.funding={'BTCUSDT':{base+16*60*M:[(base+16*60*M,.0001)]}}
    def change_month(self,t):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):return np.array([100.6,100.8,100.3,100.6,100.,1e6])
class Guard:
    def eligible(self,s,side,t):return True
    def correlation(self,*args):return 0.
row={'ts':bar,'decision_ts':bar+30_000,'feature_known_ts':bar,'observation_id':'extend_test',
     'symbol':'BTCUSDT','contract':'BTCUSDT','side':1,'signal_close':100.6,'atr':2.,
     'stop_price':99.5,'level':100.5,'break_ts':bar,'touch_ts':bar+30_000,'score':1.,'rank':1,
     'rvol':2.,'liquidity_rank':1,'risk_multiplier':1.,'tick_status':'verified',
     'entry_exec_ts':bar+35_001,'raw_entry_5s':100.6,'suffix_high':100.8,
     'suffix_low':100.3,'suffix_close':100.6}
def run(overnight,maxhold):
    sc={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':1.,'leverage':10,
        'max_hold_minutes':maxhold,'allow_overnight':overnight}
    return eng.simulate(sc,pd.DataFrame([row]),'2026-05-01','2026-05-02',market=Market(),guard=Guard(),save=False)
sm,_,trades,_,fund=run(True,240)
assert sm['valid_for_comparison'] and len(trades)==1 and trades[0]['reason']=='time240'
assert trades[0]['exit_ts']==bar+240*M and len(fund)==1 and fund[0]['actual_charge']>0
assert np.isclose(trades[0]['funding'],fund[0]['actual_charge'])
sm2,_,trades2,_,fund2=run(False,240)
assert sm2['valid_for_comparison'] and trades2[0]['reason']=='day_close' and not fund2
assert trades2[0]['exit_ts']==base+15*60*M+55*M
sm3,_,trades3,_,fund3=run(True,720)
assert sm3['valid_for_comparison'] and trades3[0]['reason']=='time720'
assert trades3[0]['exit_ts']==bar+720*M and len(fund3)==1
report={'four_hour_limit':True,'overnight_carry':True,'historic_funding_applied':True,
        'twelve_hour_limit':True,'non_overnight_uses_day_close':True,'note':'Minute-level risk and exit assumptions still apply.'}
(HERE/'延长持仓合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXTENDED_ENGINE_SYNTHETICS_PASS',json.dumps(report),flush=True)
