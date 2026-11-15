"""Independently check 2023 OI time selection and unit-return arithmetic."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent
SNAP = H / '2023基础冻结结果'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    point_path, result_path = H / '2023持仓量逐点核验.json', H / '2023持仓量跨期对照.json'
    point = json.loads(point_path.read_text(encoding='utf-8'))
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert result['inputs']['point_audit_sha256'] == sha(point_path) and result['inputs']['code_sha256'] == sha(H / 'evaluate_2023_oi.py')
    detail_path, ledger_path = H / '2023一秒观察持仓量逐笔.csv', H / '2023一秒观察已核验账本.csv'
    assert result['inputs']['detail_sha256'] == sha(detail_path) and result['inputs']['ledger_csv_sha256'] == sha(ledger_path)
    with detail_path.open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    with ledger_path.open(encoding='utf-8', newline='') as f:
        ledger = {(r['observation_id'], r['variant']): r for r in csv.DictReader(f)}
    assert len(detail) == len(ledger) and len({(r['observation_id'], r['variant']) for r in detail}) == len(detail)
    points = {(x['symbol'], int(x['ts'])): x for x in point['points']}
    for row in detail:
        original = ledger[(row['observation_id'], row['variant'])]
        decision, now, old = int(row['decision_ts']), int(row['oi_t0']), int(row['oi_previous'])
        assert now == (decision - 900000) // 300000 * 300000 and old == now - 3600000
        flags = []
        for sym in ('BTCUSDT', 'ETHUSDT'):
            x, y = points.get((sym, now)), points.get((sym, old))
            if not x or not y or x['status'] != 'verified' or y['status'] != 'verified':
                flags.append(None)
            else:
                flags.append(float(x['values'][0]) > float(y['values'][0]))
        gate = None if any(x is None for x in flags) else all(flags)
        assert row['gate'] == ('' if gate is None else str(gate))
        assert (row['oi_status'] == 'verified') == (gate is not None)
        for field in ('entry_ts', 'entry_fill', 'exit_raw', 'side', 'funding'):
            assert near(row[field], original[field])
        assert near(row['net'], original['net_per_unit_notional'])
    baseline = json.loads((SNAP / 'support/2023一秒观察对照.json').read_text(encoding='utf-8'))['rows']
    checked = 0
    for out in result['rows']:
        lev, strategy, slip = out['leverage'], out['strategy'], out['exit_slippage_pct'] / 100
        universe = [r for r in detail if r['variant'].endswith(f'_{lev}x')]
        chosen = universe if strategy == 'base' else [r for r in universe if r['gate'] == 'True']
        ref = next(r for r in baseline if r['leverage'] == lev)
        unknown = ref['one_second_observation']['unknown'] + (sum(not r['gate'] for r in universe) if strategy == 'oi_gate' else 0)
        no_order = ref['known_no_order'] + (sum(r['gate'] == 'False' for r in universe) if strategy == 'oi_gate' else 0)
        assert out['unknown_candidates'] == unknown and out['known_no_order'] == no_order and len(chosen) + unknown + no_order == 146
        vals, days = [], set()
        for r in chosen:
            side, entry, raw = int(float(r['side'])), float(r['entry_fill']), float(r['exit_raw'])
            exit_ = raw * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r['funding']))
            days.add(datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(vals), sum(x > 0 for x in vals)
        pos, neg = math.fsum(x for x in vals if x > 0), -math.fsum(x for x in vals if x < 0)
        assert out['known_trades'] == n and out['net_wins'] == wins and out['active_utc_days'] == len(days)
        assert near(out['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(out['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(out['profit_factor'], pos / neg if neg else None)
        checked += 1
    out = {'all_checks_pass': True, 'groups_checked': checked, 'detail_rows_checked': len(detail),
           'oi_points_checked': len(points), 'official_sample_errors': point['official_errors'],
           'result_sha256': sha(result_path), 'audit_code_sha256': sha(Path(__file__)),
           'note': 'Independent historical time and arithmetic checks, not real-time availability or account testing.'}
    (H / '2023持仓量门独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('YEAR2023_OI_AUDIT', checked, len(detail), flush=True)


if __name__ == '__main__':
    main()
