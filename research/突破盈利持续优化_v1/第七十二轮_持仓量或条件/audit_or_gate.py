"""Independently verify point times, OR selection, fees and unknown counts."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent
R69 = H.parent / '第六十九轮_一秒观察持仓量门'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    result_path = H / '或条件跨期对照.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    detail_path = H / '或条件逐笔明细.csv'
    assert result['code_sha256'] == sha(H / 'evaluate_or_gate.py') and result['plan_sha256'] == sha(H / '冻结研究方案.md')
    assert result['detail_sha256'] == sha(detail_path) and len(result['rows']) == 48
    with detail_path.open(encoding='utf-8', newline='') as f:
        detail = list(csv.DictReader(f))
    assert len({(r['year'], r['observation_id'], r['variant']) for r in detail}) == len(detail)
    point_checks = 0
    for year in ('2024', '2026'):
        folder = R69 / f'{year}冻结结果'
        manifest = json.loads((folder / '冻结哈希.json').read_text(encoding='utf-8'))
        path = folder / f'{year}持仓量逐点核验.json'
        assert sha(path) == manifest['files'][path.name]
        points = json.loads(path.read_text(encoding='utf-8'))
        lookup = {(r['symbol'], int(r['ts'])): r for r in points['points']}
        for r in (x for x in detail if x['year'] == year):
            now, previous, decision = int(r['oi_t0']), int(r['oi_previous']), int(r['decision_ts'])
            assert now == (decision - 900000) // 300000 * 300000 and previous == now - 3600000
            flags = []
            for sym, field in (('BTCUSDT', 'btc_up'), ('ETHUSDT', 'eth_up')):
                a, b = lookup.get((sym, now)), lookup.get((sym, previous))
                if not a or not b or a['status'] != 'verified' or b['status'] != 'verified':
                    flag = None
                else:
                    flag = float(a['values'][0]) > float(b['values'][0])
                assert r[field] == ('' if flag is None else str(flag))
                flags.append(flag)
            unknown = any(v is None for v in flags)
            conditions = {'and_gate': None if unknown else all(flags), 'or_gate': None if unknown else any(flags),
                          'one_only': None if unknown else sum(flags) == 1}
            for name, value in conditions.items():
                assert r[name] == ('' if value is None else str(value))
            point_checks += 1
    checked = 0
    for row in result['rows']:
        year, lev, cohort, slip = row['year'], row['leverage'], row['cohort'], row['exit_slippage_pct'] / 100
        universe = [x for x in detail if x['year'] == year and x['variant'].endswith(f'_{lev}x')]
        chosen = universe if cohort == 'base' else [x for x in universe if x[cohort] == 'True']
        base = next(x for x in result['rows'] if x['year'] == year and x['leverage'] == lev and x['cohort'] == 'base' and x['exit_slippage_pct'] == .05)
        unknown = base['unknown_candidates'] + (sum(x[cohort] == '' for x in universe) if cohort != 'base' else 0)
        no_order = base['known_no_order'] + (sum(x[cohort] == 'False' for x in universe) if cohort != 'base' else 0)
        assert row['unknown_candidates'] == unknown and row['known_no_order'] == no_order
        assert len(chosen) + unknown + no_order == (119 if year == '2024' else 39)
        vals, days = [], set()
        for r in chosen:
            side, entry, raw = int(r['side']), float(r['entry_fill']), float(r['exit_raw'])
            exit_ = raw * (1 - side * slip)
            vals.append(side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r['funding']))
            days.add(datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date())
        n, wins = len(vals), sum(x > 0 for x in vals)
        positive, negative = math.fsum(x for x in vals if x > 0), -math.fsum(x for x in vals if x < 0)
        assert row['known_trades'] == n and row['net_wins'] == wins and row['active_utc_days'] == len(days)
        assert near(row['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(row['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(row['profit_factor'], positive / negative if negative else None)
        assert near(row['worst_net_pct_notional'], 100 * min(vals) if vals else None)
        checked += 1
    out = {'all_checks_pass': True, 'groups_checked': checked, 'detail_rows_checked': len(detail),
           'point_decisions_checked': point_checks, 'result_sha256': sha(result_path),
           'audit_code_sha256': sha(Path(__file__)),
           'note': 'Independently recomputed historical rules and costs; OI real-time release and actual executions remain unknown.'}
    (H / '或条件独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OI_OR_AUDIT', checked, len(detail), point_checks, flush=True)


if __name__ == '__main__':
    main()
