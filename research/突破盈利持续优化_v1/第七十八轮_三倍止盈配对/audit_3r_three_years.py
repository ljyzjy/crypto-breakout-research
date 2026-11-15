"""Independently audit matched 3R aggregate arithmetic and candidate unknowns."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '三时段三倍止盈合并对照.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'summarize_3r_three_years.py') and len(result['rows']) == 8
    details, prior = [], {}
    for year in ('2023', '2024', '2026'):
        folder = H / f'{year}冻结结果'
        mf = folder / '冻结哈希.json'
        assert sha(mf) == result['source_snapshot_sha256'][year]
        m = json.loads(mf.read_text(encoding='utf-8'))
        csv_name, json_name = f'support/{year}三倍止盈配对逐笔.csv', f'support/{year}三倍止盈配对对照.json'
        assert sha(folder / csv_name) == m['files'][csv_name] and sha(folder / json_name) == m['files'][json_name]
        with (folder / csv_name).open(encoding='utf-8', newline='') as f:
            details.extend(csv.DictReader(f))
        prior[year] = json.loads((folder / json_name).read_text(encoding='utf-8'))['rows']
    for row in result['rows']:
        lev, cohort, target = row['leverage'], row['cohort'], row['exit_target']
        group = [r for r in details if int(r['leverage']) == lev and r['cohort'] == cohort]
        vals = [float(r['old_net' if target == '2r' else 'new_net']) for r in group]
        n, wins = len(vals), sum(v > 0 for v in vals)
        pos, neg = math.fsum(v for v in vals if v > 0), -math.fsum(v for v in vals if v < 0)
        days = {datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date() for r in group}
        unknown = sum(next(x['unknown_candidates'] for x in prior[y] if x['leverage'] == lev and x['cohort'] == cohort and x['exit_target'] == target and x['exit_slippage_pct'] == .05) for y in prior)
        assert row['known_trades'] == n and row['net_wins'] == wins and row['active_utc_days'] == len(days) and row['unknown_candidates'] == unknown
        assert near(row['net_win_rate_pct'], 100 * wins / n if n else None)
        assert near(row['mean_net_pct_notional'], 100 * math.fsum(vals) / n if n else None)
        assert near(row['profit_factor'], pos / neg if neg else None)
    out = {'all_checks_pass': True, 'groups_checked': len(result['rows']), 'detail_rows_checked': len(details),
           'result_sha256': sha(path), 'audit_code_sha256': sha(Path(__file__)),
           'note': 'Equal-notional paired units only, no shared account or independent blind test.'}
    (H / '三时段三倍止盈独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('THREE_R_THREE_YEAR_AUDIT', len(result['rows']), len(details), flush=True)


if __name__ == '__main__':
    main()
