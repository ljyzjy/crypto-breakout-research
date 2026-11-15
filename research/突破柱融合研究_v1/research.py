"""Isolated retrospective research. Never writes to the original project or calls order APIs."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
GE = Path(r'C:\Users\WIN11\Documents\Codex\2026-11-12\ge')
P2 = GE / 'outputs' / 'feature-research-phase2'
P3 = GE / 'outputs' / 'feature-research-phase3' / 'account'
sys.path.insert(0, str(P3))
from account_market import Market, RankTrendGuard
from engine import simulate

spec = importlib.util.spec_from_file_location('phase2_readonly', P2 / 'data_io.py')
pio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pio)
M = 60_000
Q = 15 * M
START = int(pd.Timestamp('2025-07-01', tz='UTC').timestamp() * 1000)
END = int(pd.Timestamp('2026-04-27', tz='UTC').timestamp() * 1000)
WARM = START - 24 * 60 * M
GRID = np.arange(WARM, END, M, dtype=np.int64)
assert len(GRID) % 15 == 0 and WARM % Q == 0


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False,
        default=lambda v: v.item() if isinstance(v, np.generic) else str(v)), encoding='utf-8')


def load_dense(contract):
    raw = pio.load_minutes(contract, WARM, END)
    cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']
    if raw.ts.duplicated().any():
        raise ValueError('duplicate minute: ' + contract)
    d = raw.set_index('ts').reindex(GRID)
    a = d[cols].to_numpy(float)
    o, h, l, c, v, qv, n = a.T
    valid = np.isfinite(a[:, :6]).all(axis=1) & (a[:, :6] > 0).all(axis=1)
    valid &= (h >= np.maximum.reduce([o, l, c])) & (l <= np.minimum.reduce([o, h, c]))
    return a, valid


def calculate(a, valid):
    """Prior complete quarter bands/ATR and same-progress trade-count ratio."""
    count = len(a) // 15
    x = a.reshape(count, 15, 7)
    ok = valid.reshape(count, 15)
    qok = ok.all(axis=1)
    qh = np.where(qok, np.where(ok, x[:, :, 1], -np.inf).max(axis=1), np.nan)
    ql = np.where(qok, np.where(ok, x[:, :, 2], np.inf).min(axis=1), np.nan)
    qc = np.where(qok, x[:, -1, 3], np.nan)
    hi = pd.Series(qh).shift(1).rolling(16, min_periods=16).max().to_numpy()
    lo = pd.Series(ql).shift(1).rolling(16, min_periods=16).min().to_numpy()
    prev = pd.Series(qc).shift(1).to_numpy()
    tr = np.maximum.reduce([qh - ql, abs(qh - prev), abs(ql - prev)])
    tr[~qok | ~np.isfinite(prev)] = np.nan
    atr = pd.Series(tr).rolling(14, min_periods=14).mean().shift(1).to_numpy()
    trade_valid = ok & np.isfinite(x[:, :, 6]) & (x[:, :, 6] > 0)
    prefix = np.cumsum(np.where(trade_valid, x[:, :, 6], np.nan), axis=1)
    previous = prefix.copy()
    previous[~qok | ~trade_valid.all(axis=1), :] = np.nan
    avg = pd.DataFrame(previous).shift(1).rolling(20, min_periods=20).mean().to_numpy()
    with np.errstate(invalid='ignore', divide='ignore'):
        ratio = prefix / avg
    ratio[~np.isfinite(ratio) | (avg <= 0)] = np.nan
    return {'upper': np.repeat(hi, 15), 'lower': np.repeat(lo, 15),
            'atr': np.repeat(atr, 15), 'ratio': ratio.ravel(), 'qvalid': qok,
            'current_prefix_valid': np.logical_and.accumulate(ok, axis=1).ravel()}


def smoke_checks():
    # Disturb future minutes of the current quarter and all later bars. No
    # metric known at the selected decision may depend on those changes.
    rng = np.random.default_rng(8128)
    n = 50 * 15
    c = 100 + np.cumsum(rng.normal(0, .01, n))
    a = np.column_stack([c, c+.1, c-.1, c, np.ones(n), np.ones(n), np.full(n, 10.)])
    valid = np.ones(n, dtype=bool)
    cut = 35*15+4
    x = calculate(a, valid)
    b = a.copy(); b[cut+1:, 1] += 10; b[cut+1:, 6] *= 12
    y = calculate(b, valid)
    for field in ('upper', 'lower', 'atr', 'ratio'):
        assert np.isclose(x[field][cut], y[field][cut], equal_nan=True), field
    assert np.isclose(x['ratio'][cut], 1.0)
    valid2 = valid.copy(); valid2[34*15+14] = False
    assert np.isnan(calculate(a, valid2)['ratio'][cut])
    valid3 = valid.copy(); valid3[35*15+1] = False
    assert not calculate(a, valid3)['current_prefix_valid'][cut]
    a2 = a.copy(); a2[34*15+14, 6] = 0
    assert np.isnan(calculate(a2, valid)['ratio'][cut])
    return {'prefix_future_perturbation': True, 'equal_progress_ratio': True,
            'missing_or_zero_prior_count_rejected': True,
            'missing_current_prefix_rejected': True}


def build_signals():
    checks = smoke_checks()
    mapping = pio.load_mapping()
    for s in ['BTCUSDT', 'ETHUSDT']:
        if not mapping.get(s): raise ValueError('missing reference mapping: ' + s)
    refs = {}
    for sym in ['BTCUSDT', 'ETHUSDT']:
        a, valid = load_dense(mapping[sym])
        f = calculate(a, valid)
        refs[sym] = {'close': a[:, 3].copy(), 'valid': valid.copy(), **f}
    guard = RankTrendGuard()
    rankframe = pd.read_parquet(P3 / 'hourly-ranks.parquet')
    ranks = {(int(r.hour), r.symbol, int(r.side)): r for r in rankframe.itertuples()}
    quarantine = pio.load_quarantine()
    reasons = Counter(); records = []
    for symbol, contract in sorted(mapping.items()):
        if not contract: continue
        a, valid = load_dense(contract)
        f = calculate(a, valid)
        # If an earlier minute in this quarter is missing, the first crossing
        # is unknowable; never silently designate a later minute as the first.
        prefix_valid = f['current_prefix_valid']
        long = valid & prefix_valid & (a[:, 3] > f['upper'])
        short = valid & prefix_valid & (a[:, 3] < f['lower'])
        cross = np.flatnonzero(long | short)
        if not len(cross): continue
        first = cross[np.r_[True, np.diff(cross // 15) != 0]]
        previous_admitted = -10**18
        for i in first:
            t0 = int(GRID[i]); decision = t0 + M; entry = decision + M
            if not START <= decision < END: continue
            reasons['quarter_first_breaks'] += 1
            if symbol not in guard.pools.get(decision // 86_400_000 * 86_400_000, set()):
                reasons['not_in_daily_pool'] += 1; continue
            if decision >= quarantine.get(symbol, {}).get('known_ts', 10**18):
                reasons['known_quarantine'] += 1; continue
            if t0 - previous_admitted < 60*M:
                reasons['event_cooldown'] += 1; continue
            previous_admitted = t0
            if entry >= (t0 // Q + 1)*Q:
                reasons['entry_not_inside_quarter'] += 1; continue
            side = 1 if long[i] else -1
            if not guard.eligible(symbol, side, decision):
                reasons['rank_or_trend'] += 1; continue
            atr = float(f['atr'][i]); close = float(a[i, 3])
            if not np.isfinite(atr) or atr <= 0:
                reasons['missing_prior_atr'] += 1; continue
            stop = float(a[i, 2] - .1*atr if side == 1 else a[i, 1] + .1*atr)
            distance = side * (close - stop)
            if distance <= 0 or distance > 1.5*atr or 2*distance/close < .006:
                reasons['original_stop_cost_gate'] += 1; continue
            rank = ranks.get((decision//3_600_000*3_600_000, symbol, side))
            if rank is None:
                raise ValueError('Guard and rank mismatch')
            ratios = [float(refs[s]['ratio'][i]) for s in ['BTCUSDT', 'ETHUSDT']]
            known = all(np.isfinite(r) for r in ratios)
            active = bool(known and all(r >= 1.5 for r in ratios))
            sync = bool(active and all(refs[s]['valid'][i] and
                       (refs[s]['close'][i] > refs[s]['upper'][i] if side == 1 else
                        refs[s]['close'][i] < refs[s]['lower'][i])
                       for s in ['BTCUSDT', 'ETHUSDT']))
            rec = {'ts': entry, 'decision_ts': decision, 'feature_known_ts': decision,
                'observation_id': f'{symbol}|{t0}|{side}', 'symbol': symbol,
                'contract': contract, 'side': side, 'signal_close': close,
                'atr': atr, 'stop_price': stop,
                'level': float(f['upper'][i] if side == 1 else f['lower'][i]),
                'break_ts': t0, 'touch_ts': t0, 'quarter_start': t0//Q*Q,
                'hour': int(rank.hour), 'score': float(rank.score), 'rank': int(rank.rank),
                'rvol': float(rank.rvol), 'liquidity_rank': int(rank.liquidity_rank),
                'risk_multiplier': 1., 'btc_ratio': ratios[0], 'eth_ratio': ratios[1],
                'activity_known': known, 'activity_pass': active, 'sync_pass': sync}
            records.append(rec)
        print('SIGNALS', symbol, 'cumulative', len(records), flush=True)
    df = pd.DataFrame(records).sort_values(['ts','symbol']).reset_index(drop=True)
    if df.empty: raise ValueError('No signals passed the fixed base rules')
    assert (df.ts == df.decision_ts + M).all()
    assert (df.decision_ts == df.break_ts + M).all()
    assert (df.ts < df.quarter_start + Q).all()
    assert (df.feature_known_ts <= df.decision_ts).all()
    assert (~df.sync_pass | df.activity_pass).all()
    df.to_parquet(HERE/'signals.parquet', index=False)
    reasons['base_candidates'] = len(df)
    reasons['activity_unknown'] = int((~df.activity_known).sum())
    reasons['activity_pass'] = int(df.activity_pass.sum())
    reasons['sync_pass'] = int(df.sync_pass.sum())
    write_json(HERE/'signal_audit.json', {'synthetic_checks': checks, 'counts': dict(reasons),
        'signal_file_sha256': hashlib.sha256((HERE/'signals.parquet').read_bytes()).hexdigest(),
        'implementation_note': 'A signal-generation-only dry run was stopped before any account outcomes after noticing that a missing early minute could obscure the first crossing; the current implementation rejects incomplete current-quarter prefixes.',
        'study_scope': 'retrospective; past outcomes had already been viewed'})
    print('SIGNALS_READY', json.dumps(dict(reasons)), flush=True)
    return df, guard


def run_accounts(df, guard):
    scenarios = [
        {'id': 'main', 'fee': .0005, 'slippage': .0005, 'delay_minutes': 0},
        {'id': 'double', 'fee': .001, 'slippage': .001, 'delay_minutes': 0},
        {'id': 'delay1', 'fee': .0005, 'slippage': .0005, 'delay_minutes': 1},
    ]
    cohorts = [('early_base', df), ('early_activity', df[df.activity_pass]),
               ('early_sync', df[df.sync_pass])]
    reports = []
    for name, sig in cohorts:
        for scenario in scenarios:
            summary, curve, trades, entries, funding = simulate(scenario, sig, '2025-07-01',
                '2026-04-26', market=Market(), guard=guard, save=False, run_id=name)
            if summary.get('valid_for_comparison') and len(trades):
                ledger = abs(float(summary['final_equity']) - 1000. - sum(t['net'] for t in trades))
                assert ledger < 1e-6, (name, scenario['id'], ledger)
            else:
                ledger = None
            summary['net_win_rate_pct'] = summary['win_rate'] if trades else None
            summary['ledger_check_error'] = ledger
            if entries:
                summary['entered_during_breakout_quarter'] = sum(e['ts'] < (e['break_ts']//Q+1)*Q for e in entries)
                assert all(e['feature_known_ts'] <= e['decision_ts'] and e['ts'] >= e['decision_ts']+M for e in entries)
            else: summary['entered_during_breakout_quarter'] = 0
            stem = HERE / f'{name}_{scenario["id"]}'
            write_json(str(stem)+'_summary.json', summary)
            write_json(str(stem)+'_trades.json', trades)
            write_json(str(stem)+'_entries.json', entries)
            write_json(str(stem)+'_funding.json', funding)
            curve.to_parquet(str(stem)+'_curve.parquet', index=False)
            reports.append(summary)
            print('ACCOUNT', name, scenario['id'], json.dumps({k:summary.get(k) for k in
                 ['trades','return_pct','max_drawdown','valid_for_comparison','issues']}), flush=True)
    write_json(HERE/'all_results.json', reports)
    cols = ['run_id','scenario','signal_candidates','trades','net_win_rate_pct','net_pnl',
            'return_pct','max_drawdown','intrabar_stress_dd','profit_factor',
            'entered_during_breakout_quarter','valid_for_comparison','issues']
    pd.DataFrame(reports).reindex(columns=cols).to_csv(HERE/'对照结果.csv', index=False, encoding='utf-8-sig')


if __name__ == '__main__':
    signal, guard = build_signals()
    run_accounts(signal, guard)
    print('RESEARCH_COMPLETE', flush=True)
