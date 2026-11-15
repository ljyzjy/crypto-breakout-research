"""Synthetic margin, sizing and conservative liquidation-path checks."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
P3=Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase3\account')
sys.path.insert(0,str(P3))
spec=importlib.util.spec_from_file_location('leveraged_test_engine',HERE/'leveraged_engine.py')
eng=importlib.util.module_from_spec(spec);sys.modules[spec.name]=eng;spec.loader.exec_module(eng)
M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
default=np.array([100.6,101.,100.2,100.6,100.,1e6])
class Market:
    def __init__(self,bars):self.bars=bars;self.funding={}
    def change_month(self,ts):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):return np.array(self.bars.get(t,default),float)
class Guard:
    def eligible(self,s,side,t):return True
    def correlation(self,*args):return 0.
row={'ts':base+2*M,'decision_ts':base+M,'feature_known_ts':base+M,'observation_id':'synthetic',
     'symbol':'BTCUSDT','contract':'BTCUSDT','side':1,'signal_close':100.6,'atr':2.,
     'stop_price':99.,'level':100.5,'break_ts':base,'touch_ts':base,'score':1.,'rank':1,
     'rvol':2.,'liquidity_rank':1,'risk_multiplier':1.}
def run(leverage,bars=None,stop_shock=0.):
    sc={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':2.,
        'leverage':leverage,'stop_shock':stop_shock}
    result,_,trades,entries,funding=eng.simulate(sc,pd.DataFrame([row]),'2026-05-01','2026-05-01',
        market=Market(bars or {}),guard=Guard(),save=False)
    assert result['valid_for_comparison'] and len(trades)==len(entries)==1
    t=trades[0]
    assert abs(t['isolated_margin']-t['entry_notional']/leverage)<1e-9
    assert entries[0]['planned_loss']<=entries[0]['known_equity']*.0025+1e-9
    assert abs(result['net_pnl']-t['net'])<1e-8
    return t

stable=[run(x) for x in (5,10,20)]
assert max(t['entry_notional'] for t in stable)-min(t['entry_notional'] for t in stable)<1e-9
assert max(t['net'] for t in stable)-min(t['net'] for t in stable)<1e-9
assert stable[0]['isolated_margin']>stable[1]['isolated_margin']>stable[2]['isolated_margin']

# Same minute crosses both stop and the 20x mark-based proxy; 10x is not close to proxy.
shock={base+4*M:[100.6,101.,95.,96.,100.,1e6]}
liq=run(20,shock);stop=run(10,shock)
assert liq['reason']=='liquidation_proxy' and liq['ambiguous'] and liq['liquidation_penalty']>0
assert stop['reason']=='stop' and stop['liquidation_penalty']==0
assert liq['net'] < -liq['planned_risk']
gap=run(20,{base+4*M:[95.,96.,94.,95.,100.,1e6]})
assert gap['reason']=='liquidation_proxy_gap' and gap['net'] < -gap['planned_risk']
badstop=run(10,shock,stop_shock=.002)
assert badstop['net']<stop['net']
row.update(side=-1, stop_price=102.2, level=100.7)
short_shock={base+4*M:[100.6,106.,100.2,105.,100.,1e6]}
short_liq=run(20,short_shock);short_stop=run(10,short_shock)
assert short_liq['reason']=='liquidation_proxy' and short_liq['ambiguous']
assert short_stop['reason']=='stop' and short_liq['net'] < -short_liq['planned_risk']
report={'same_notional_same_pnl_for_5_10_20':True,'isolated_margin_is_notional_over_leverage':True,
        'risk_budget_includes_cost_and_gap_buffer':True,'liquidation_precedes_stop_when_same_minute':True,
        'proxy_penalty_recorded':True,'gap_can_exceed_planned_loss':True,'stress_stop_shock':True,
        'short_liquidation_proxy_and_stop':True}
(HERE/'高杠杆引擎合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('LEVERAGE_SYNTHETICS_PASS',json.dumps(report),flush=True)
