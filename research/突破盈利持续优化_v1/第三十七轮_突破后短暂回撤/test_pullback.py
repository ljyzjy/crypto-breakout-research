"""Synthetic chronology and future-perturbation checks for the frozen rule."""
import json,shutil
from pathlib import Path
import numpy as np,pandas as pd
import prepare_pullback_candidates as candidate
from pullback_paths import simulate_pullback

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent.parent
e={'side':1,'trigger_minute':0,'quarter_end':60_000,'upper':100.,'lower':90.,'decision_ts':1000,
   'signal_close':100.1,'entry_exec_ts':6000,'raw_entry_5s':100.3,'second_ref_ts':11000,'second_ref_price':100.2,
   'stop_price':99.,'atr':2.,'level':100.}
def tape(rows):return pd.DataFrame([{'transact_time':t,'price':p,'agg_trade_id':i} for i,(t,p) in enumerate(rows)])
t=tape([(1000,100.1),(6000,100.3),(11000,100.2),(16000,100.15),(21000,103.5),(26000,103.4),(60000,103.3),(65000,103.2)])
for lev in (10,20):
    p=simulate_pullback(e,t,lev,False)
    assert p['status']=='verified' and p['entry_ts']==16000 and p['exit_signal_ts']==21000 and p['exit_ts']==26000
    assert np.isclose(p['entry_fill'],100.15*1.0005) and np.isclose(p['exit_fill'],103.4*.9995)
bad=tape([(1000,100.1),(6000,100.3),(11000,100.2),(16000,98.8),(21000,98.7),(60000,100.),(65000,100.)])
assert simulate_pullback(e,bad,20,False)['reason']=='filled_beyond_risk_budget'
invalid={**e,'second_ref_price':100.4};u=tape([(1000,100.1),(6000,100.3),(11000,100.4),(16000,100.2),(60000,100.3),(65000,100.4)])
assert simulate_pullback(invalid,u,10,False)['status']=='pullback_condition_mismatch'
broken={**e,'second_ref_price':99.9};u=tape([(1000,100.1),(6000,100.3),(11000,99.9),(16000,100.2),(60000,100.3),(65000,100.4)])
assert simulate_pullback(broken,u,10,False)['status']=='pullback_condition_mismatch'
short={**e,'side':-1,'signal_close':89.9,'raw_entry_5s':89.7,'second_ref_price':89.8,'stop_price':91.,'level':90.}
v=tape([(1000,89.9),(6000,89.7),(11000,89.8),(16000,89.85),(21000,86.5),(26000,86.6),(60000,86.7),(65000,86.8)])
assert simulate_pullback(short,v,20,False)['entry_ts']==16000
fast=tape([(1000,100.1),(6000,100.3),(11000,100.2),(16000,100.15),(17000,99.9),(19000,99.8),(24000,99.75),(60000,100.),(65000,100.)])
p=simulate_pullback(e,fast,10,True)
assert p['reason']=='failed_breakout' and p['exit_signal_ts']==19000 and p['exit_ts']==24000

work=ROOT/'work'/'pullback37_lookahead_test';work.mkdir(parents=True,exist_ok=True)
shutil.copyfile(HERE/'冻结研究方案.json',work/'冻结研究方案.json')
expected=pd.read_parquet(HERE/'短暂回撤事前候选.parquet').sort_values('observation_id').reset_index(drop=True)
reader=pd.read_parquet;original_here=candidate.HERE
def perturbed(path,*args,**kwargs):
    d=reader(path,*args,**kwargs)
    if Path(path).name=='动态池延迟市价路径.parquet':
        for k in ('exit_ts','exit_raw','exit_fill','exit_signal_ts'):
            if k in d:d[k]=123456789
        d['reason']='future_perturbed';d['status']='future_status_perturbed'
    return d
try:
    candidate.HERE=work;candidate.pd.read_parquet=perturbed;candidate.main()
finally:
    candidate.pd.read_parquet=reader;candidate.HERE=original_here
got=reader(work/'短暂回撤事前候选.parquet').sort_values('observation_id').reset_index(drop=True)
pd.testing.assert_frame_equal(expected,got,check_dtype=True)
out={'all_candidates_checked':len(expected),'old_exit_prices_times_reasons_and_status_perturbed':True,
     'candidate_set_and_fields_unchanged':True,'p10_observed_before_p15_entry':True,'long_and_short':True,
     'both_leverage_gates':True,'unsafe_delayed_fill_is_not_free_cancellation':True,
     'non_pullback_and_broken_level_rejected':True,'fast_exit_requires_continuous_observation':True}
(HERE/'回撤入场时序与未来扰动核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('PULLBACK37_TEST',json.dumps(out),flush=True)
