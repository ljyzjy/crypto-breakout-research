"""Independently verify paired and distinct-entry group calculations."""
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
    summary_path = H / '入场构成事后诊断.json'
    data = json.loads(summary_path.read_text(encoding='utf-8'))
    detail = H / '逐笔构成诊断.csv'
    assert data['code_sha256'] == sha(H / 'diagnose_entry_composition.py') and data['detail_sha256'] == sha(detail)
    with detail.open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    assert len({(r['year'], r['leverage'], r['observation_id']) for r in rows}) == len(rows)
    checked = 0
    for s in data['rows']:
        group = [r for r in rows if r['year'] == s['year'] and r['leverage'] == str(s['leverage'])]
        for category, column, output in [('common', 'old_net_notional', 'common_five_second'),
                                         ('common', 'new_net_notional', 'common_one_second'),
                                         ('new_only', 'new_net_notional', 'new_only_one_second'),
                                         ('old_only', 'old_net_notional', 'old_only_five_second')]:
            vals = [float(r[column]) for r in group if r['group'] == category]
            expected = s[output]
            assert len(vals) == expected['trades'] and sum(x > 0 for x in vals) == expected['net_wins']
            if vals:
                assert near(100 * math.fsum(vals) / len(vals), expected['mean_net_pct_notional'])
            checked += 1
        times = [(int(r['new_entry_ts']) - int(r['old_entry_ts'])) / 1000 for r in group if r['group'] == 'common']
        assert not times or near(statistics.median(times), s['median_new_minus_old_entry_seconds'])
    out = {'all_checks_pass': True, 'group_calculations_checked': checked, 'detail_rows_checked': len(rows),
           'result_sha256': sha(summary_path), 'audit_code_sha256': sha(Path(__file__)),
           'note': 'Paired descriptive decomposition, not an independent test or causal estimate.'}
    (H / '入场构成独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ENTRY_COMPOSITION_AUDIT', checked, len(rows), flush=True)


if __name__ == '__main__':
    main()
