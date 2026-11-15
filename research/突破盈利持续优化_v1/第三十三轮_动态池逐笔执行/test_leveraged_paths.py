"""Verify 20x parity with the audited prior engine and 10x gate differences."""
import importlib.util,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from leveraged_paths import known_precheck,simulate_path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('original_unit_paths',HERE.parent/'第二十九轮_秒级延迟与失败退出'/'unit_paths.py')
old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
e={'side':1,'trigger_minute':0,'quarter_end':60_000,'upper':100.,'lower':90.,'decision_ts':1000,
   'signal_close':100.1,'entry_exec_ts':6000,'raw_entry_5s':100.2,'stop_price':99.,'atr':2.,'level':100.}
def tape(rows):return pd.DataFrame([{'transact_time':t,'price':p,'agg_trade_id':i} for i,(t,p) in enumerate(rows)])
t=tape([(1000,100.1),(6000,100.2),(11000,100.3),(12000,99.9),(13000,100.1),
        (14000,99.9),(16000,99.8),(21000,99.9),(60000,100.1),(65000,100.1)])
for fail in (False,True):
    assert known_precheck(e,20)==old.known_precheck(e)
    assert simulate_path(e,t,20,fail)==old.simulate_path(e,t,2.,fail)
wide={**e,'stop_price':98.2}
assert known_precheck(wide,20)=='reference_liquidation_buffer_known' and known_precheck(wide,10) is None
assert simulate_path(e,t,20,True)['reason']=='failed_breakout'
unsafe=tape([(1000,100.1),(6000,100.2),(11000,98.8),(16000,98.7),(60000,100.),(65000,100.)])
assert simulate_path(e,unsafe,10,False)['reason']=='filled_beyond_risk_budget'
short={**e,'side':-1,'signal_close':89.9,'raw_entry_5s':89.8,'stop_price':91.,'level':90.}
short_t=tape([(1000,89.9),(6000,89.8),(11000,89.7),(16000,87.0),(21000,87.1),(60000,87.2),(65000,87.3)])
for fail in (False,True):assert simulate_path(short,short_t,20,fail)==old.simulate_path(short,short_t,2.,fail)
out={'20x_engine_parity':True,'10x_distinct_preentry_buffer':True,'both_sides':True,
     'delayed_unsafe_fill_pays_exit_cost':True,'failed_breakout_confirmation':True}
(HERE/'十与二十倍逐笔路径合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('UNIVERSE33_LEVERAGE_PATH_TEST',json.dumps(out),flush=True)
