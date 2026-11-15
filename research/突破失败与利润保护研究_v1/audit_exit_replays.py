"""Independently reconcile account curves, costs and causal rule events."""
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
NOV = HERE.parent.parent / 'work' / 'breakout_november_2026'
NORM = NOV / 'normalized'
M = 60_000
all_results = json.loads((HERE / '全部策略账户结果.json').read_text(encoding='utf-8'))
assert len(all_results) == 60
raw_requests = defaultdict(list)
event_counts = Counter()
max_dd_error = 0.
max_ledger_error = 0.
trade_checks = 0

for sm in all_results:
    stem = f"{sm['period']}_{sm['run_id']}_{sm['scenario']}"
    trades = json.loads((HERE / f'{stem}_trades.json').read_text(encoding='utf-8'))
    entries = json.loads((HERE / f'{stem}_entries.json').read_text(encoding='utf-8'))
    funding = json.loads((HERE / f'{stem}_funding.json').read_text(encoding='utf-8'))
    curve = pd.read_parquet(NOV / 'study_curves' / f'{stem}.parquet')
    assert sm['valid_for_comparison'] and len(curve) == sm['expected_calendar_minutes'], stem
    assert len(trades) == len(entries) == sm['trades'], stem
    equity = np.r_[1000., curve.equity.to_numpy()]
    dd = np.max(100 * (1 - equity / np.maximum.accumulate(equity)))
    max_dd_error = max(max_dd_error, abs(dd - sm['max_drawdown']))
    max_ledger_error = max(max_ledger_error, abs(sm['final_equity'] - 1000 - sum(t['net'] for t in trades)))
    assert abs(sum(t['funding'] for t in trades) - sum(f['actual_charge'] for f in funding)) < 1e-7, stem
    assert sum(t['net'] > 0 for t in trades) == sm['winning_trade_count'], stem
    assert np.isclose(sum(t['net'] for t in trades), sm['net_pnl'], atol=1e-7), stem
    trade_map = {t['observation_id']: t for t in trades}
    assert len(trade_map) == len(trades), stem
    for t in trades:
        side = 1 if t['side'] == 'long' else -1
        qty, fee, slip = t['qty'], sm['fee'], sm['slippage']
        assert np.isclose(t['entry'], t['raw_entry'] * (1 + side * slip), rtol=1e-11), stem
        assert np.isclose(t['exit'], t['raw_exit'] * (1 - side * slip), rtol=1e-11), stem
        assert np.isclose(t['entry_fee'], qty * t['entry'] * fee, rtol=1e-11), stem
        assert np.isclose(t['exit_fee'], qty * t['exit'] * fee, rtol=1e-11), stem
        assert np.isclose(t['gross'], side * qty * (t['raw_exit'] - t['raw_entry']), atol=1e-8), stem
        assert np.isclose(t['net'], side * qty * (t['exit'] - t['entry']) - t['fees'] - t['funding'], atol=1e-8), stem
        assert np.isclose(t['target'], t['entry'] + side * 2 * t['initial_price_risk'], rtol=1e-11), stem
        assert t['entry_ts'] >= t['decision_ts'] + M, stem
        if t['reason'] == 'failed_breakout':
            assert t['failure_known_ts'] and t['exit_ts'] >= t['failure_known_ts'] + M, stem
        trade_checks += 1
    for e in sm['rule_events']:
        t = trade_map[e['id']]
        side = 1 if t['side'] == 'long' else -1
        assert e['effective_ts'] >= e['known_ts'] + M, stem
        event_counts[e['kind']] += 1
        if e['kind'] == 'lock_scheduled':
            assert e['known_ts'] % (5 * M) == 0 and e['known_ts'] - 5 * M >= t['entry_ts'], stem
            assert side * (e['close'] - t['entry']) + 1e-12 >= t['initial_price_risk'], stem
        elif e['kind'] == 'failure_scheduled':
            assert e['known_ts'] == t['quarter_end_ts'], stem
            assert side * (e['close'] - t['break_level']) <= 1e-12, stem
        elif e['kind'] == 'lock_applied':
            assert np.isclose(e['new_stop'], t['entry'] + side * .5 * t['initial_price_risk'], rtol=1e-11), stem
            assert side * (e['new_stop'] - e['old_stop']) > 0, stem
        else:
            raise AssertionError(e['kind'])
        if sm['period'] != 'old_dynamic' and e['kind'].endswith('_scheduled'):
            raw_requests[t['contract']].append((e['known_ts'] - M, e['close'], stem))

assert max_dd_error < 1e-8 and max_ledger_error < 1e-6
raw_checks = 0
for contract, requests in raw_requests.items():
    data = pd.read_parquet(NORM / f'{contract}_klines.parquet', columns=['ts', 'close']).set_index('ts')
    assert data.index.is_unique
    for minute, expected, stem in requests:
        assert minute in data.index and np.isclose(float(data.at[minute, 'close']), expected, rtol=1e-11), stem
        raw_checks += 1

report = {'accounts_reconciled': len(all_results), 'trade_records_checked': trade_checks,
          'rule_event_counts': dict(event_counts), 'rule_closes_checked_against_public_minutes': raw_checks,
          'public_minute_close_scope': 'fixed 2026 periods including November; old dynamic event math audited separately',
          'max_drawdown_error_percentage_points': max_dd_error, 'max_ledger_error_usdt': max_ledger_error,
          'limitations': 'Checks share underlying public minutes and cannot verify real market fills.'}
(HERE / '退出规则与账户独立对账.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('ACCOUNT_AND_RULE_AUDIT_PASS', json.dumps(report, ensure_ascii=False), flush=True)
