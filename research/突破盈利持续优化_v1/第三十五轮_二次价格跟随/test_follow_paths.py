"""Test P5/P10 observation and genuinely later P15 market-entry execution."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from follow_paths import simulate_follow
HERE=Path(__file__).resolve().parent
e={'side':1,'trigger_minute':0,'quarter_end':60_000,'upper':100.,'lower':90.,'decision_ts':1000,
   'signal_close':100.1,'entry_exec_ts':6000,'raw_entry_5s':100.2,'second_ref_ts':11000,'second_ref_price':100.3,
   'stop_price':99.,'atr':2.,'level':100.}
def tape(rows):return pd.DataFrame([{'transact_time':t,'price':p,'agg_trade_id':i} for i,(t,p) in enumerate(rows)])
t=tape([(1000,100.1),(6000,100.2),(11000,100.3),(16000,100.35),(21000,103.5),(26000,103.4),(60000,103.3),(65000,103.2)])
for L in (10,20):
 r=simulate_follow(e,t,L,False);assert r['status']=='verified' and r['entry_ts']==16000 and r['exit_signal_ts']==21000 and r['exit_ts']==26000
 assert np.isclose(r['entry_fill'],100.35*1.0005) and np.isclose(r['exit_fill'],103.4*.9995)
bad=tape([(1000,100.1),(6000,100.2),(11000,100.3),(16000,98.8),(21000,98.7),(60000,100.),(65000,100.)])
r=simulate_follow(e,bad,20,False);assert r['status']=='verified' and r['reason']=='filled_beyond_risk_budget' and r['exit_ts']==21000
down={**e,'second_ref_price':100.1};u=tape([(1000,100.1),(6000,100.2),(11000,100.1),(16000,100.2),(60000,100.3),(65000,100.4)])
assert simulate_follow(down,u,10,False)['status']=='follow_condition_mismatch'
short={**e,'side':-1,'signal_close':89.9,'raw_entry_5s':89.8,'second_ref_price':89.7,'stop_price':91.,'level':90.}
v=tape([(1000,89.9),(6000,89.8),(11000,89.7),(16000,89.65),(21000,86.5),(26000,86.6),(60000,86.7),(65000,86.8)])
assert simulate_follow(short,v,20,False)['entry_ts']==16000
out={'p10_observed_before_p15_entry':True,'long_and_short':True,'both_leverage_gates':True,
     'unsafe_delayed_fill_is_not_free_cancellation':True,'non_follow_rejected':True}
(HERE/'二次跟随路径合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('FOLLOW35_PATH_TEST',json.dumps(out),flush=True)
