"""Independently check the post-hoc profit concentration arithmetic."""
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def main():
    path = H / '持仓量门收益集中度事后诊断.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['code_sha256'] == sha(H / 'diagnose_gate_concentration.py') and len(data['rows']) == 4
    for out in data['rows']:
        year, lev = out['year'], out['leverage']
        folder = H / f'{year}冻结结果'
        manifest = json.loads((folder / '冻结哈希.json').read_text(encoding='utf-8'))
        file = folder / f'{year}一秒观察持仓量逐笔.csv'
        assert sha(file) == manifest['files'][file.name]
        with file.open(encoding='utf-8', newline='') as f:
            rows = [r for r in csv.DictReader(f) if r['variant'].endswith(f'_{lev}x') and r['gate'] == 'True']
        vals = [float(x['net']) * 100 for x in rows]
        assert len(vals) == out['trades'] and near(statistics.median(vals), out['median_net_pct'])
        assert near(math.fsum(vals) / len(vals), out['mean_net_pct'])
        best = max(range(len(vals)), key=vals.__getitem__)
        without = [x for i, x in enumerate(vals) if i != best]
        assert near(math.fsum(without) / len(without), out['mean_without_best_pct'])
        positives = [x for x in vals if x > 0]
        assert near(100 * vals[best] / math.fsum(positives), out['largest_win_share_of_gross_profits_pct'])
        stressed = []
        for i, r in enumerate(rows):
            if i == best:
                continue
            side, entry, raw = int(float(r['side'])), float(r['entry_fill']), float(r['exit_raw'])
            exit_ = raw * (1 - side * .00075)
            stressed.append(100 * (side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - float(r['funding'])))
        assert near(math.fsum(stressed) / len(stressed), out['mean_without_same_best_exit_slip_0075_pct'])
    result = {'all_checks_pass': True, 'groups_checked': len(data['rows']), 'diagnostic_sha256': sha(path),
              'audit_code_sha256': sha(Path(__file__))}
    (H / '收益集中度独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OI_PROFIT_DIAGNOSTIC_AUDIT', len(data['rows']), flush=True)


if __name__ == '__main__':
    main()
