"""Rebuild structural stops and reconcile wider-stop and extended-hold accounts."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent
EXT=HERE.parent/'第九轮_突破后延长持仓'
M=60_000
features=[];checked=0
for year in (2024,2026):
    f=pd.read_parquet(HERE/f'{year}结构止损特征_train.parquet');features.append(f)
    norm=ROOT/'work'/('breakout_november_2026' if year==2026 else 'breakout_2024_11')/'normalized'
    for contract,g in f.groupby('contract'):
        raw=pd.read_parquet(norm/f'{contract}_klines.parquet',columns=['ts','high','low']).set_index('ts')
        for r in g.itertuples(index=False):
            d=raw.reindex(np.arange(int(r.quarter_start),int(r.trigger_minute),M,dtype=np.int64))
            assert len(d)>0 and np.isfinite(d.to_numpy(float)).all()
            expected=float(d.low.min()-.1*r.atr if int(r.side)==1 else d.high.max()+.1*r.atr)
            assert np.isclose(expected,r.prefix_stop,rtol=1e-11)
            assert np.isclose(r.level-r.side*r.atr,r.atr_stop,rtol=1e-11)
            assert r.feature_known_ts<=r.decision_ts
            checked+=1
features=pd.concat(features,ignore_index=True).set_index('observation_id')
curves=ROOT/'work'/'breakout_profit_research'/'curves'
summaries=[*HERE.glob('*_summary.json'),*EXT.glob('*_summary.json')]
trades_checked=0;max_error=0.;max_dd=0.;settlements=0
for path in summaries:
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    trades=json.loads((path.parent/f'{stem}_trades.json').read_text(encoding='utf-8'))
    fund=json.loads((path.parent/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(curves/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(trades)==sm['trades']
    eq=np.r_[1000.,curve.equity.to_numpy()];dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    max_dd=max(max_dd,abs(dd-sm['max_drawdown']))
    max_error=max(max_error,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(x['actual_charge'] for x in fund))<1e-7
    settlements+=len(fund)
    for t in trades:
        side=1 if t['side']=='long' else -1;slip=sm['slippage']
        assert t['entry_ts']>=t['decision_ts']+5000
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*slip),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert t['exit_ts']<=t['entry_bar_ts']+sm['max_hold_minutes']*M
        if path.parent==HERE:
            f=features.loc[t['observation_id']]
            expected=f.prefix_stop if sm['run_id'].startswith('prefix_') else f.atr_stop
            assert np.isclose(t['initial_stop'],expected,rtol=1e-11)
        trades_checked+=1
assert max_error<1e-6 and max_dd<1e-8
report={'structural_signal_features_checked':checked,'accounts_checked':len(summaries),
        'trade_records_checked':trades_checked,'funding_settlements_recorded':settlements,
        'max_ledger_error_usdt':max_error,'max_drawdown_error_pct_points':max_dd,
        'limit':'Funding, marks, and execution depend on the same public archives and modeled minute-level fills.'}
(HERE/'持仓与结构止损独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('EXTENDED_STOP_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
