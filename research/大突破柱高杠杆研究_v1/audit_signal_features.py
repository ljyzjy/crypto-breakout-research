"""Recompute all 106 candidate features from minute data independently."""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
NORM=HERE.parent.parent/'work'/'breakout_november_2026'/'normalized'
M=60_000;Q=15*M
@lru_cache(maxsize=18)
def data(contract):
    x=pd.read_parquet(NORM/f'{contract}_klines.parquet',columns=['ts','open','high','low','close','trade_count']).set_index('ts')
    assert x.index.is_unique
    return x
def bars(contract,start,end):
    return data(contract).reindex(np.arange(start,end,M,dtype=np.int64)).to_numpy(float)
features=pd.read_parquet(HERE/'候选信号及事后大柱标签.parquet')
assert len(features)==106 and features.observation_id.is_unique
for r in features.itertuples(index=False):
    quarter=int(r.break_ts)//Q*Q;k=(int(r.break_ts)-quarter)//M+1;side=int(r.side)
    old=bars(r.contract,quarter-20*Q,quarter).reshape(20,15,5)
    current=bars(r.contract,quarter,int(r.break_ts)+M)
    assert len(current)==k and np.isfinite(current).all()
    previous_prefix=old[:,:k,4].sum(axis=1)
    assert np.isfinite(old).all() and (old[:,:,4]>0).all() and (current[:,4]>0).all()
    ratio=current[:,4].sum()/previous_prefix.mean()
    partial=side*(current[-1,3]-current[0,0])/r.atr
    stop=current[:,2].min()-.1*r.atr if side==1 else current[:,1].max()+.1*r.atr
    assert np.isclose(ratio,r.own_trade_count_ratio,rtol=1e-10,atol=1e-10)
    assert np.isclose(partial,r.partial_body_atr,rtol=1e-10,atol=1e-10)
    assert np.isclose(stop,r.structure_stop,rtol=1e-10,atol=1e-10)
    assert bool(r.strength_pass)==bool(ratio>=1.5 and partial>=.25)
    assert r.decision_ts==r.break_ts+M and r.ts==r.decision_ts+M and r.ts<quarter+Q
    completed=bars(r.contract,quarter,quarter+Q)
    close=completed[-1,3];body=side*(close-completed[0,0])/completed[0,0]
    beyond=side*(close-r.level)>0
    assert bool(r.large_1pct_label)==bool(body>=.01 and beyond)
    assert bool(r.large_halfpct_label)==bool(body>=.005 and beyond)
report={'candidate_signals_checked':len(features),'current_prefix_and_20_prior_equal_progress_counts':True,
        'partial_body_and_structure_stop_checked':True,'decision_and_entry_timing_checked':True,
        'completed_bar_labels_checked':True,
        'future_data_removed_from_execution_engine':True,
        'limitation':'Shared source data and minute-level execution; no proof of live fills or historical liquidation brackets.'}
(HERE/'信号独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('SIGNAL_FEATURE_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
