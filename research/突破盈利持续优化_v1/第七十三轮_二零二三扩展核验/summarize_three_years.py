"""Summarize verified 2023/2024/2026 unit paths without imputing unknowns."""
import csv
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path

getcontext().prec = 32
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    rows, prior, sources = [], {}, {}
    for year in ('2023', '2024', '2026'):
        folder = H / '2023持仓量冻结结果' if year == '2023' else P / f'第六十九轮_一秒观察持仓量门/{year}冻结结果'
        manifest = folder / '冻结哈希.json'
        info = json.loads(manifest.read_text(encoding='utf-8'))
        csv_path = folder / f'{year}一秒观察持仓量逐笔.csv'
        json_path = folder / ('2023持仓量跨期对照.json' if year == '2023' else f'{year}一秒观察持仓量对照.json')
        assert info['all_checks_pass'] and sha(csv_path) == info['files'][csv_path.name] and sha(json_path) == info['files'][json_path.name]
        with csv_path.open(encoding='utf-8', newline='') as f:
            rows.extend({'year': year, **r} for r in csv.DictReader(f))
        prior[year] = json.loads(json_path.read_text(encoding='utf-8'))['rows']
        sources[year] = sha(manifest)
    output = []
    for lev in (10, 20):
        universe = [x for x in rows if x['variant'].endswith(f'_{lev}x')]
        for cohort in ('base', 'oi_gate'):
            chosen = universe if cohort == 'base' else [r for r in universe if r['gate'] == 'True']
            values = [D(r['net']) for r in chosen]
            n, wins = len(values), sum(x > 0 for x in values)
            positive = sum((v for v in values if v > 0), D(0))
            negative = -sum((v for v in values if v < 0), D(0))
            unknown = sum(next(x['unknown_candidates'] for x in prior[y] if x['leverage'] == lev and x['strategy'] == cohort and x['exit_slippage_pct'] == .05) for y in prior)
            days = {datetime.fromtimestamp(int(r['entry_ts']) / 1000, timezone.utc).date() for r in chosen}
            output.append({'leverage': lev, 'cohort': cohort, 'known_trades': n, 'net_wins': wins,
                           'net_win_rate_pct': float(D(100) * wins / n) if n else None,
                           'mean_net_pct_notional': float(D(100) * sum(values, D(0)) / n) if n else None,
                           'profit_factor': float(positive / negative) if negative else None,
                           'active_utc_days': len(days), 'unknown_candidates': unknown,
                           'worst_net_pct_notional': float(D(100) * min(values)) if n else None})
    result = {'rows': output, 'source_snapshot_sha256': sources, 'code_sha256': sha(Path(__file__)),
              'note': 'Equal-notional unit opportunities across unequal historical windows; not independent OOS or compounded account return.'}
    (H / '三时段合并单位机会.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in output:
        if row['leverage'] == 20:
            print('YEAR3_UNIT_SUMMARY', row, flush=True)


if __name__ == '__main__':
    main()
