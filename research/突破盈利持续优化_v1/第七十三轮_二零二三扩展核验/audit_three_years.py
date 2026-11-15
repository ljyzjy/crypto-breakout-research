"""Independently audit the equal-notional three-period unit summaries."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '三时段合并单位机会.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'summarize_three_years.py')
    all_rows, prior = [], {}
    for y in ('2023', '2024', '2026'):
        folder = H / '2023持仓量冻结结果' if y == '2023' else P / f'第六十九轮_一秒观察持仓量门/{y}冻结结果'
        mf = folder / '冻结哈希.json'
        assert sha(mf) == result['source_snapshot_sha256'][y]
        manifest = json.loads(mf.read_text(encoding='utf-8'))
        detail = folder / f'{y}一秒观察持仓量逐笔.csv'
        summary = folder / ('2023持仓量跨期对照.json' if y == '2023' else f'{y}一秒观察持仓量对照.json')
        assert sha(detail) == manifest['files'][detail.name] and sha(summary) == manifest['files'][summary.name]
        with detail.open(encoding='utf-8', newline='') as f:
            all_rows.extend({'year': y, **r} for r in csv.DictReader(f))
        prior[y] = json.loads(summary.read_text(encoding='utf-8'))['rows']
    for out in result['rows']:
        lev, cohort = out['leverage'], out['cohort']
        rows = [r for r in all_rows if r['variant'].endswith(f'_{lev}x') and (cohort == 'base' or r['gate'] == 'True')]
        vals = [float(r['net']) for r in rows]
        n, wins = len(vals), sum(v > 0 for v in vals)
        pos, neg = math.fsum(v for v in vals if v > 0), -math.fsum(v for v in vals if v < 0)
        days = {datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date() for r in rows}
        unknown = sum(next(x['unknown_candidates'] for x in prior[y] if x['leverage'] == lev and x['strategy'] == cohort and x['exit_slippage_pct'] == .05) for y in prior)
        assert out['known_trades'] == n and out['net_wins'] == wins and out['active_utc_days'] == len(days) and out['unknown_candidates'] == unknown
        assert near(out['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(out['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(out['profit_factor'], pos / neg if neg else None)
        assert near(out['worst_net_pct_notional'], 100 * min(vals) if n else None)
    audit = {'all_checks_pass': True, 'groups_checked': len(result['rows']), 'source_rows_checked': len(all_rows),
             'result_sha256': sha(path), 'audit_code_sha256': sha(Path(__file__)),
             'note': 'Historical equal-notional opportunities; not independent validation or an account equity curve.'}
    (H / '三时段合并独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('YEAR3_UNIT_AUDIT', len(result['rows']), len(all_rows), flush=True)


if __name__ == '__main__':
    main()
