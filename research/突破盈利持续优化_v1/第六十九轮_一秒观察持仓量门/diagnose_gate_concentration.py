"""Post-hoc concentration diagnostics, using already frozen gate trades only."""
import csv
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
    output = []
    for year in ('2024', '2026'):
        folder = H / f'{year}冻结结果'
        manifest = json.loads((folder / '冻结哈希.json').read_text(encoding='utf-8'))
        name = f'{year}一秒观察持仓量逐笔.csv'
        path = folder / name
        assert manifest['all_checks_pass'] and sha(path) == manifest['files'][name]
        with path.open(encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        for lev in (10, 20):
            chosen = [x for x in rows if x['variant'].endswith(f'_{lev}x') and x['gate'] == 'True']
            vals = sorted(D(x['net']) for x in chosen)
            n = len(vals)
            assert n > 1
            wins, losses = [x for x in vals if x > 0], [x for x in vals if x < 0]
            med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
            stressed = []
            for r in chosen:
                side, entry = D(r['side']), D(r['entry_fill'])
                exit_ = D(r['exit_raw']) * (1 - side * D('.00075'))
                stressed.append(side * (exit_ - entry) / entry - D('.0005') - D('.0005') * exit_ / entry - D(r['funding']))
            max_i = max(range(n), key=lambda i: D(chosen[i]['net']))
            stress_without_same_best = (sum(stressed) - stressed[max_i]) / D(n - 1)
            output.append({'year': year, 'leverage': lev, 'trades': n, 'net_values_pct_notional': [float(100 * x) for x in vals],
                           'median_net_pct': float(100 * med), 'mean_net_pct': float(100 * sum(vals) / n),
                           'mean_win_pct': float(100 * sum(wins) / len(wins)) if wins else None,
                           'mean_loss_pct': float(100 * sum(losses) / len(losses)) if losses else None,
                           'largest_win_share_of_gross_profits_pct': float(100 * max(vals) / sum(wins)) if wins else None,
                           'mean_without_best_pct': float(100 * (sum(vals) - max(vals)) / D(n - 1)),
                           'mean_without_same_best_exit_slip_0075_pct': float(100 * stress_without_same_best)})
    result = {'rows': output, 'code_sha256': sha(Path(__file__)),
              'note': 'Post-hoc diagnostics on very small selected samples, not a trading filter or account simulation.'}
    (H / '持仓量门收益集中度事后诊断.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in output:
        if row['leverage'] == 20:
            print('OI_PROFIT_DIAGNOSTIC', row, flush=True)


if __name__ == '__main__':
    main()
