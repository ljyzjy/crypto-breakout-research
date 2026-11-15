"""Reconcile prior dynamic-pool account runs, retaining their separate scope."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
WORK=HERE.parent.parent/'work'/'breakout_forward_2026'
PREV=HERE.parent/'突破柱融合研究_v1'
first=pd.read_parquet(PREV/'signals.parquet');first=first[first.sync_pass].set_index('observation_id')
confirm=pd.read_parquet(HERE/'历史确认信号.parquet').set_index('observation_id')
results=json.loads((HERE/'历史稳健性全部结果.json').read_text(encoding='utf-8'))
assert len(results)==12
maxdd=0.;maxnet=0.
for s in results:
    stem=f"historical_{s['run_id']}_{s['scenario']}"
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(WORK/f'{stem}_curve.parquet')
    assert s['valid_for_comparison'] and len(curve)==432_000 and len(trades)==s['trades']
    eq=np.r_[1000.,curve.equity.to_numpy()]
    dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    maxdd=max(maxdd,abs(dd-s['max_drawdown']))
    maxnet=max(maxnet,abs(s['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(s['funding_cost']-sum(t['funding'] for t in trades))<1e-7
    signal=confirm if s['run_id']=='confirm_1r' else first
    for t in trades:
        row=signal.loc[t['observation_id']]
        assert t['entry_ts']>=int(row.decision_ts)+60_000 and row.feature_known_ts<=row.decision_ts
        if s['scenario']=='main':assert t['entry_ts']<int(row.quarter_start)+900_000
        side=1 if t['side']=='long' else -1
        target=t['entry']+side*s['target_r']*side*(t['entry']-t['stop'])
        assert np.isclose(target,t['target'],rtol=1e-10,atol=1e-10)
assert maxdd<1e-8 and maxnet<1e-6
out={'accounts_reconciled':len(results),'max_drawdown_error':maxdd,'max_ledger_error':maxnet,
 'limits':'Historical already inspected and dynamic pool differs from later fixed-pool experiment.'}
(HERE/'历史账户对账.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('HIST_ACCOUNT_AUDIT_PASS',json.dumps(out,ensure_ascii=False))
