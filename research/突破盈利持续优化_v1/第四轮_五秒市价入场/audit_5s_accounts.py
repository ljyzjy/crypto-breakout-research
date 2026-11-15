"""Reconcile 5s entry and cost-space account records against tick excerpts."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent
other=HERE.parent/'第五轮_五秒波动与成本空间'
ticks=pd.read_parquet(HERE/'五秒价格摘要_train.parquet').set_index('observation_id')
assert ticks.index.is_unique and ticks.status.eq('verified').all()
features=pd.concat([pd.read_parquet(HERE.parent/'第二轮_成本空间与即时成交'/f'{year}新特征与事后标签.parquet') for year in (2024,2026)],ignore_index=True).set_index('observation_id')
assert features.index.is_unique
curves=ROOT/'work'/'breakout_profit_research'/'curves'
summaries=[*HERE.glob('*_summary.json'),*other.glob('*_summary.json')]
count=0;max_error=0.;max_dd=0.
for path in summaries:
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    trades=json.loads((path.parent/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((path.parent/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((path.parent/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(curves/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(trades)==len(entries)==sm['trades']
    eq=np.r_[1000.,curve.equity.to_numpy()];dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    max_dd=max(max_dd,abs(dd-sm['max_drawdown']))
    max_error=max(max_error,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in funding))<1e-7
    for t in trades:
        tick=ticks.loc[t['observation_id']];f=features.loc[t['observation_id']]
        side=1 if t['side']=='long' else -1;slip=sm['slippage'];fee=sm['fee']
        assert t['entry_ts']==tick.entry_exec_ts and t['entry_ts']>=t['decision_ts']+5000
        assert np.isclose(t['raw_entry'],tick.raw_entry_5s,rtol=1e-12)
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*slip),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(slip+extra)),rtol=1e-11)
        assert np.isclose(t['entry_fee'],t['qty']*t['entry']*fee,rtol=1e-11)
        assert np.isclose(t['exit_fee'],t['qty']*t['exit']*fee+t['liquidation_penalty'],rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert np.isclose(t['target'],t['entry']+side*sm['target_r']*t['initial_price_risk'],rtol=1e-11)
        if sm['run_id'].startswith('vol_'):
            assert f.atr/f.signal_close>=.005
            if '_ne_' in sm['run_id']:assert f.partial_body_atr<=1.
            if '_room_' in sm['run_id']:assert f.signal_stop_fraction>=.0045
        count+=1
assert max_error<1e-6 and max_dd<1e-8
report={'five_second_tick_records':len(ticks),'accounts_checked':len(summaries),'trade_records_checked':count,
        'max_ledger_error_usdt':max_error,'max_drawdown_error_pct_points':max_dd,
        'limits':'Entry price is a trade-based reference plus modeled slippage; later exits remain minute-level.'}
(HERE/'五秒账户独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('FIVE_SECOND_ACCOUNT_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
