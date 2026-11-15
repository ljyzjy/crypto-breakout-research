"""Independently reconcile each account, trade cost, margin, and bar-hit label."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
CURVES=HERE.parent.parent/'work'/'breakout_november_2026'/'leverage_curves'
results=json.loads((HERE/'全部账户结果.json').read_text(encoding='utf-8'))
features=pd.read_parquet(HERE/'候选信号及事后大柱标签.parquet').set_index('observation_id')
assert len(results)==144 and features.index.is_unique
max_dd_error=0.;max_ledger_error=0.;checked=0
for sm in results:
    stem=f"{sm['period']}_{sm['run_id']}_{int(sm['position_leverage'])}x_{sm['scenario']}"
    trades=json.loads((HERE/f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries=json.loads((HERE/f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding=json.loads((HERE/f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve=pd.read_parquet(CURVES/f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve)==sm['expected_calendar_minutes']
    assert len(trades)==len(entries)==sm['trades']
    equity=np.r_[1000.,curve.equity.to_numpy()]
    dd=float(np.max(100*(1-equity/np.maximum.accumulate(equity))))
    max_dd_error=max(max_dd_error,abs(dd-sm['max_drawdown']))
    max_ledger_error=max(max_ledger_error,abs(sm['final_equity']-1000-sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades)-sum(e['actual_charge'] for e in funding))<1e-7
    assert sum(t['net']>0 for t in trades)==sm['winning_trade_count']
    leverage=float(sm['position_leverage']);fee=float(sm['fee']);slip=float(sm['slippage'])
    for e in entries:
        assert e['planned_loss']<=e['known_equity']*.0025+1e-7
        assert e['gross_after']<=e['known_equity']*2+1e-7
        assert e['aggregate_planned_loss']<=e['known_equity']*e['portfolio_risk_cap']+1e-7
    for t in trades:
        side=1 if t['side']=='long' else -1;qty=t['qty']
        assert np.isclose(t['isolated_margin'],t['entry_notional']/leverage,rtol=1e-11)
        assert np.isclose(t['entry'],t['raw_entry']*(1+side*slip),rtol=1e-11)
        extra=sm['stop_shock'] if t['reason'] in ('stop','gap_stop') else 0.
        assert np.isclose(t['exit'],t['raw_exit']*(1-side*(slip+extra)),rtol=1e-11)
        assert np.isclose(t['entry_fee'],qty*t['entry']*fee,rtol=1e-11)
        assert np.isclose(t['exit_fee'],qty*t['exit']*fee+t['liquidation_penalty'],rtol=1e-11)
        assert np.isclose(t['net'],side*qty*(t['exit']-t['entry'])-t['fees']-t['funding'],atol=1e-8)
        assert np.isclose(t['planned_risk'],t['entry_notional']*(t['initial_price_risk']/t['entry']+2*fee+2*slip+.002),rtol=1e-11)
        target=3 if sm['run_id'] in ('strength_3r','structure_3r') else 2
        assert np.isclose(t['target'],t['entry']+side*target*t['initial_price_risk'],rtol=1e-11)
        assert t['entry_ts']>=t['decision_ts']+60_000
        checked+=1
    in_quarter=[t for t in trades if t['entry_ts']<t['quarter_end_ts']]
    big=[t for t in in_quarter if bool(features.at[t['observation_id'],'large_1pct_label'])]
    assert len(in_quarter)==sm['in_original_quarter'] and len(big)==sm['large_1pct_caught']
    assert sum(t['net']>0 for t in big)==sm['large_1pct_trade_win']
    assert sum(t['reason'].startswith('liquidation_proxy') for t in trades)==sm['liquidation_proxy_count']
    assert sum(-t['net']>t['planned_risk']+1e-9 for t in trades)==sm['planned_loss_exceeded_count']
assert max_dd_error<1e-8 and max_ledger_error<1e-6
report={'accounts_checked':len(results),'trade_records_checked':checked,
        'max_drawdown_error_percentage_points':max_dd_error,'max_ledger_error_usdt':max_ledger_error,
        'entry_and_exit_slippage_and_fees_checked':True,'funding_and_margin_checked':True,
        'trade_risk_and_entry_gross_cap_checked':True,'retrospective_big_bar_hit_checked':True,
        'limits':'Accounting and labels share the archived bars; margin brackets and live execution are not independently established.'}
(HERE/'账户独立对账.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('LEVERAGED_ACCOUNTS_AUDITED',json.dumps(report,ensure_ascii=False),flush=True)
