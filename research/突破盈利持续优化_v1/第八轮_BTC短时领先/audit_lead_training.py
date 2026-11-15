"""Recompute all pre-trigger returns and reconcile the 12 training accounts."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent.parent
M=60_000
checked=0
for year in (2024,2026):
    norm=ROOT/'work'/('breakout_november_2026' if year==2026 else 'breakout_2024_11')/'normalized'
    signals=pd.read_parquet(HERE/f'{year}触价前市场特征.parquet')
    def close(c):return pd.read_parquet(norm/f'{c}_klines.parquet',columns=['ts','close']).set_index('ts').close
    btc=close('BTCUSDT');eth=close('ETHUSDT')
    for contract,g in signals.groupby('contract'):
        asset=close(contract)
        for r in g.itertuples(index=False):
            t=int(r.trigger_minute)
            for series,stored in [(btc,r.btc_prev_return),(eth,r.eth_prev_return),(asset,r.asset_prev_return)]:
                if t-M not in series.index or t-2*M not in series.index:
                    assert np.isnan(stored);continue
                expected=series.at[t-M]/series.at[t-2*M]-1
                assert np.isclose(expected,stored,rtol=1e-10,atol=1e-12,equal_nan=True)
            assert r.lead_features_known_ts==t and t<=r.decision_ts
            checked+=1
curve_dir=ROOT/'work'/'breakout_profit_research'/'curves'
accounts=list(HERE.glob('*_summary.json'));trades_checked=0;err=0.;dd_err=0.
for path in accounts:
    sm=json.loads(path.read_text(encoding='utf-8'));stem=path.name.removesuffix('_summary.json')
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    funding=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(curve_dir/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes'] and len(trades)==sm['trades']
    eq=np.r_[1000.,curve.equity.to_numpy()];dd=np.max(100*(1-eq/np.maximum.accumulate(eq)))
    dd_err=max(dd_err,abs(dd-sm['max_drawdown']))
    err=max(err,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(f['actual_charge'] for f in funding))<1e-7
    for t in trades:
        side=1 if t['side']=='long' else -1
        assert t['entry_ts']>=t['decision_ts']+5000
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*sm['slippage']),rtol=1e-11)
        assert np.isclose(t['net'],side*t['qty']*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        trades_checked+=1
assert err<1e-6 and dd_err<1e-8
report={'signals_checked':checked,'accounts_checked':len(accounts),'trade_records_checked':trades_checked,
        'max_ledger_error_usdt':err,'max_drawdown_error_pct_points':dd_err,
        'limit':'Repeated scenarios use overlapping historical events and do not represent independent trades.'}
(HERE/'领先筛选独立核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('LEAD_AUDIT_PASS',json.dumps(report,ensure_ascii=False),flush=True)
