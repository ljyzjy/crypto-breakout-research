"""Synthetic causal timing, leg accounting, stop priority and funding tests."""
import importlib.util
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase3\account')
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m);return m
eng=load('partial_synthetic',HERE/'partial_engine.py')
old=load('partial_control_old',HERE.parent/'第九轮_突破后延长持仓'/'extended_engine.py')
M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)

class Market:
    def __init__(self,side=1,gap=False,early=False,funding=False):
        self.side=side;self.gap=gap;self.early=early
        self.funding={'BTCUSDT':{base+3*M:[(base+3*M,side*.001)]}} if funding else {}
    def change_month(self,t):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):
        if t==base+M:v=[100.6,102.,100.5,101.6]
        elif t==base+2*M:v=[101.5,101.7,99.4 if self.early else 101.3,101.5]
        elif t==base+3*M:
            v=([100.8,101.,100.7,100.8] if self.gap else [101.5,101.7,100.8,101.])
        else:v=[100.6,100.8,100.3,100.6]
        if self.side==-1:v=[201.2-v[0],201.2-v[2],201.2-v[1],201.2-v[3]]
        return np.array(v+[100.,1e6])
class Guard:
    def eligible(self,s,side,t):return True
    def correlation(self,*args):return 0.
def row(side):
    return {'ts':base,'decision_ts':base+30_000,'feature_known_ts':base,'observation_id':'synthetic',
      'symbol':'BTCUSDT','contract':'BTCUSDT','side':side,'signal_close':100.6,'atr':2.,
      'stop_price':99.5 if side==1 else 101.7,'level':100.5 if side==1 else 100.7,
      'break_ts':base,'touch_ts':base+30_000,'score':1.,'rank':1,'rvol':2.,'liquidity_rank':1,
      'risk_multiplier':1.,'tick_status':'verified','entry_exec_ts':base+35_001,'raw_entry_5s':100.6,
      'suffix_high':100.8 if side==1 else 100.9,'suffix_low':100.3 if side==1 else 100.4,'suffix_close':100.6}
def run(module,side=1,gap=False,early=False,funding=False,partial=True):
    sc={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':2.,'leverage':10,
        'max_hold_minutes':240,'allow_overnight':True,'partial_exit':partial}
    return module.simulate(sc,pd.DataFrame([row(side)]),'2026-05-01','2026-05-01',
                           market=Market(side,gap,early,funding),guard=Guard(),save=False)
for side in [1,-1]:
    sm,_,trades,_,fund=run(eng,side,funding=True)
    assert sm['valid_for_comparison'] and len(trades)==1 and len(fund)==2,(sm,trades,fund)
    t=trades[0]
    assert t['reason']=='stop' and t['partial_known_ts']==base+2*M and t['partial_ts']==base+3*M
    assert t['partial_effective_ts']==t['partial_known_ts']+M
    assert np.isclose(t['partial_qty'],.5*t['qty'])
    expected=side*(t['partial_qty']*(t['partial_fill']-t['entry'])+
                    (t['qty']-t['partial_qty'])*(t['final_fill']-t['entry']))-t['entry_fee']-t['exit_fee']-t['funding']
    assert np.isclose(t['net'],expected) and np.isclose(sm['net_pnl'],expected)
    assert np.isclose(t['funding'],sum(f['actual_charge'] for f in fund))
    assert np.isclose(sum(f['qty'] for f in fund),t['qty'])
    g=run(eng,side,gap=True)[2][0]
    assert g['reason']=='gap_stop' and g['partial_qty']==0
    e=run(eng,side,early=True)[2][0]
    assert e['reason']=='stop' and e['partial_qty']==0 and e['exit_ts']==base+3*M
    a=run(eng,side,partial=False);b=run(old,side,partial=False)
    assert a[0]['valid_for_comparison'] and b[0]['valid_for_comparison']
    for key in ['net','gross','fees','funding','exit_ts','raw_exit','qty','reason']:
        av=a[2][0][key];bv=b[2][0][key]
        assert (av==bv if isinstance(av,str) else np.isclose(av,bv)),(key,av,bv)
report={'long_short_checked':True,'one_minute_confirmation_and_extra_delay':True,'funding_at_partial_boundary':True,
        'original_stop_priority':True,'gap_past_new_stop_full_exit':True,'entry_fee_once_and_two_exit_legs':True,
        'control_matches_previous_engine':True,'note':'Synthetic data only; remaining exits retain minute resolution.'}
(HERE/'分批保护合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PARTIAL_SYNTHETICS_PASS',json.dumps(report),flush=True)
