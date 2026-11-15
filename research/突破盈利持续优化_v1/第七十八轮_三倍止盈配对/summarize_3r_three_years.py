"""Equal-notional three-period matched 2R versus 3R unit summary."""
import csv
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    details, prior, hashes = [], {}, {}
    for year in ('2023', '2024', '2026'):
        folder = H / f'{year}冻结结果'
        manifest = folder / '冻结哈希.json'
        m = json.loads(manifest.read_text(encoding='utf-8'))
        csv_name, json_name = f'support/{year}三倍止盈配对逐笔.csv', f'support/{year}三倍止盈配对对照.json'
        assert m['all_checks_pass'] and sha(folder / csv_name) == m['files'][csv_name] and sha(folder / json_name) == m['files'][json_name]
        with (folder / csv_name).open(encoding='utf-8', newline='') as f:
            details.extend(csv.DictReader(f))
        prior[year] = json.loads((folder / json_name).read_text(encoding='utf-8'))['rows']
        hashes[year] = sha(manifest)
    output = []
    for lev in (10, 20):
        for cohort in ('base', 'oi_gate'):
            group = [r for r in details if int(r['leverage']) == lev and r['cohort'] == cohort]
            for target, field in (('2r', 'old_net'), ('3r', 'new_net')):
                vals = [D(r[field]) for r in group]
                n, wins = len(vals), sum(v > 0 for v in vals)
                pos, neg = sum((v for v in vals if v > 0), D(0)), -sum((v for v in vals if v < 0), D(0))
                days = {datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date() for r in group}
                unknown = sum(next(x['unknown_candidates'] for x in prior[y] if x['leverage'] == lev and x['cohort'] == cohort and x['exit_target'] == target and x['exit_slippage_pct'] == .05) for y in prior)
                output.append({'leverage': lev, 'cohort': cohort, 'exit_target': target, 'known_trades': n, 'net_wins': wins,
                               'net_win_rate_pct': float(D(100) * wins / n) if n else None,
                               'mean_net_pct_notional': float(D(100) * sum(vals, D(0)) / n) if n else None,
                               'profit_factor': float(pos / neg) if neg else None, 'active_utc_days': len(days), 'unknown_candidates': unknown})
    out = {'rows': output, 'source_snapshot_sha256': hashes, 'code_sha256': sha(Path(__file__)),
           'note': 'Equal-notional historical units across unequal windows; no account compounding or independent OOS.'}
    (H / '三时段三倍止盈合并对照.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in output:
        if row['leverage'] == 20:
            print('THREE_R_THREE_YEAR', row, flush=True)


if __name__ == '__main__':
    main()
