"""Independently check cost components, exit reasons and holding-time groups."""
from collections import Counter
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


def main():
    result_path, detail_path = H / '成本与退出原因诊断.json', H / '成本归因逐笔.csv'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert result['code_sha256'] == sha(H / 'diagnose_costs.py') and result['detail_sha256'] == sha(detail_path)
    with detail_path.open(encoding='utf-8', newline='') as f:
        details = list(csv.DictReader(f))
    assert len({(x['year'], x['observation_id'], x['variant']) for x in details}) == len(details)
    for row in details:
        assert math.isclose(math.fsum(float(row[k]) for k in ('gross', 'entry_slip', 'exit_slip', 'fees', 'funding')),
                            float(row['net']), rel_tol=1e-10, abs_tol=1e-11)
    for out in result['rows']:
        selected = [x for x in details if x['year'] == out['year'] and x['variant'].endswith(f"_{out['leverage']}x") and
                    (out['cohort'] == 'base' or x['oi_gate'] == 'True')]
        assert len(selected) == out['trades'] and dict(Counter(x['reason'] for x in selected)) == out['exit_reasons']
        for key in ('gross', 'entry_slip', 'exit_slip', 'fees', 'funding', 'net'):
            val = 100 * math.fsum(float(x[key]) for x in selected) / len(selected)
            assert math.isclose(val, out[f'mean_{key}_pct_notional'], rel_tol=1e-10, abs_tol=1e-10)
        hold = statistics.median((int(x['exit_ts']) - int(x['entry_ts'])) / 1000 for x in selected)
        assert math.isclose(hold, out['median_holding_seconds'], rel_tol=1e-10, abs_tol=1e-10)
    out = {'all_checks_pass': True, 'groups_checked': len(result['rows']), 'path_rows_checked': len(details),
           'diagnostic_sha256': sha(result_path), 'audit_code_sha256': sha(Path(__file__)),
           'note': 'Unit arithmetic only, not actual fills or shared-account returns.'}
    (H / '成本归因独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('COST_ATTRIBUTION_AUDIT', len(result['rows']), len(details), flush=True)


if __name__ == '__main__':
    main()
