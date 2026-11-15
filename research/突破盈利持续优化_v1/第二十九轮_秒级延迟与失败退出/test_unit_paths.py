"""Synthetic tests for exact delay, reset, stop priority and failed fills."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from unit_paths import known_precheck,simulate_path
HERE=Path(__file__).resolve().parent
e={'side':1,'trigger_minute':0,'quarter_end':60_000,'upper':100.,'lower':90.,'decision_ts':1000,
   'signal_close':100.1,'entry_exec_ts':6000,'raw_entry_5s':100.2,'stop_price':99.,'atr':2.,'level':100.}
def ticks(rows):
    return pd.DataFrame([{'transact_time':t,'price':p,'agg_trade_id':i} for i,(t,p) in enumerate(rows)]).sort_values(['transact_time','agg_trade_id'])
assert known_precheck(e) is None
a=ticks([(1000,100.1),(6000,100.2),(11000,100.3),(16000,101.8),(21000,101.7),(60000,101.6),(65000,101.5)])
r=simulate_path(e,a,1.,False)
assert r['status']=='verified' and r['entry_signal_reference_ts']==6000 and r['entry_ts']==11000
assert r['reason']=='target' and r['exit_signal_ts']==16000 and r['exit_ts']==21000
assert np.isclose(r['entry_fill'],100.3*1.0005) and np.isclose(r['exit_fill'],101.7*.9995)
short={**e,'side':-1,'signal_close':89.9,'raw_entry_5s':89.8,'stop_price':91.,'level':90.}
short_ticks=ticks([(1000,89.9),(6000,89.8),(11000,89.7),(16000,88.2),(21000,88.3),(60000,88.4),(65000,88.5)])
assert known_precheck(short) is None
short_result=simulate_path(short,short_ticks,1.,False)
assert short_result['reason']=='target' and short_result['entry_ts']==11000 and short_result['exit_ts']==21000
assert np.isclose(short_result['entry_fill'],89.7*.9995) and np.isclose(short_result['exit_fill'],88.3*1.0005)
b=ticks([(1000,100.1),(6000,100.2),(11000,100.3),(12000,99.9),(13000,100.1),
         (14000,99.9),(16000,99.8),(21000,99.9),(60000,100.1),(65000,100.1)])
x=simulate_path(e,b,1.,True)
assert x['reason']=='failed_breakout' and x['exit_signal_ts']==16000 and x['exit_ts']==21000
z=simulate_path(e,b,1.,False)
assert z['reason']=='quarter_time' and z['exit_signal_ts']==60000 and z['exit_ts']==65000
c=ticks([(1000,100.1),(6000,100.2),(11000,98.8),(16000,98.7),(60000,100.),(65000,100.)])
q=simulate_path(e,c,1.,False)
assert q['status']=='verified' and q['entry_ts']==11000 and q['reason']=='filled_beyond_risk_budget' and q['exit_ts']==16000
g=ticks([(1000,100.1),(6000,100.2),(11000,100.3),(60000,98.9),(65000,98.8)])
v=simulate_path(e,g,1.,False)
assert v['reason']=='stop' and v['exit_signal_ts']==60000 and v['exit_ts']==65000
missing=ticks([(1000,100.1),(6000,100.2),(11000,100.3),(16000,101.8)])
assert simulate_path(e,missing,1.,False)['status']=='missing_delayed_exit'
report={'long_and_short':True,'observed_reference_then_extra_5s_entry':True,'trigger_then_extra_5s_exit':True,'failure_duration_resets':True,
        'entry_past_stop_not_free_cancelled':True,'same_timestamp_stop_before_expiry':True,'missing_exit_is_error':True}
(HERE/'秒级路径合成核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIT_PATH_SYNTHETIC_PASS',json.dumps(report),flush=True)
