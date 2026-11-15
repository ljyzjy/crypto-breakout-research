"""Test causal failure confirmation, delay and original stop priority."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent
sys.path.insert(0,r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\feature-research-phase3\account')
def load(name,path):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp)
    sys.modules[name]=m;sp.loader.exec_module(m);return m
eng=load('quickfail_new',HERE/'quickfail_engine.py')
old=load('quickfail_old',HERE.parent/'第六轮_柱内首次触价'/'touch_engine.py')
M=60_000;base=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000)
class Market:
    def __init__(self,side,gap=False):self.side=side;self.gap=gap;self.funding={}
    def change_month(self,t):pass
    def funding_ok(self,c,t):return True
    def bar(self,c,t,mark=False):
        v=[99.4,100.8,99.3,100.6] if self.gap and t==base+2*M else [100.6,100.8,100.3,100.6]
        if self.side==-1:v=[201.2-v[0],201.2-v[2],201.2-v[1],201.2-v[3]]
        return np.array(v+[100.,1e6])
class Guard:
    def eligible(self,*args):return True
    def correlation(self,*args):return 0.
def run(module,side=1,enabled=True,gap=False,stop=False):
    row={'ts':base,'decision_ts':base+30_000,'feature_known_ts':base,'observation_id':'quickfail_test',
      'symbol':'BTCUSDT','contract':'BTCUSDT','side':side,'signal_close':100.6,'atr':2.,
      'stop_price':99.5 if side==1 else 101.7,'level':100.5 if side==1 else 100.7,
      'break_ts':base,'touch_ts':base+30_000,'score':1.,'rank':1,'rvol':2.,'liquidity_rank':1,
      'risk_multiplier':1.,'tick_status':'verified','entry_exec_ts':base+35_001,'raw_entry_5s':100.6,
      'suffix_high':100.8 if side==1 else (101.8 if stop else 100.9),
      'suffix_low':(99.4 if stop else 100.3) if side==1 else 100.4,'suffix_close':100.4 if side==1 else 100.8}
    sc={'id':'test','fee':.0005,'slippage':.0005,'delay_minutes':0,'target_r':2.,'leverage':10,'failure_exit':enabled}
    return module.simulate(sc,pd.DataFrame([row]),'2026-05-01','2026-05-01',market=Market(side,gap),guard=Guard(),save=False)
for side in (1,-1):
    sm,_,ts,_,_=run(eng,side);assert sm['valid_for_comparison'] and len(ts)==1
    assert ts[0]['reason']=='failed_breakout' and ts[0]['failure_known_ts']==base+M and ts[0]['exit_ts']==base+2*M
    assert run(eng,side,gap=True)[2][0]['reason']=='gap_stop'
    assert run(eng,side,stop=True)[2][0]['reason']=='stop'
    a=run(eng,side,enabled=False);b=run(old,side,enabled=False)
    for k in ('entry_ts','exit_ts','reason','net','gross','fees','funding','qty'):
        x=a[2][0][k];y=b[2][0][k];assert x==y if isinstance(x,str) else np.isclose(x,y)
out={'long_short':True,'completed_minute_known_then_full_minute_delay':True,'stop_priority':True,'disabled_control_parity':True}
(HERE/'快速失败合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('QUICKFAIL_SYNTHETIC_PASS',json.dumps(out),flush=True)
