"""Independently compare locally sourced risk-cache rows to verified ZIP CSVs."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    journal = H / '2024本地风险来源记录.jsonl'
    entries = [json.loads(x) for x in journal.read_text(encoding='utf-8').splitlines()] if journal.exists() else []
    written = [x for x in entries if 'cache' in x]
    checks = []
    for item in written:
        source, path = Path(item['source']), Path(item['cache'])
        assert sha(source) == item['source_sha256'] and sha(path) == item['cache_sha256']
        cached = json.loads(path.read_text(encoding='utf-8'))
        assert cached['status'] == 'verified' and cached['sha256'] == item['source_sha256']
        assert (cached['kind'], cached['contract'], cached['month']) == (item['kind'], item['contract'], item['month'])
        selected = {int(r['ts']): r for r in cached['rows']}
        assert len(selected) == len(cached['rows'])
        found = {}
        with zipfile.ZipFile(source) as z:
            members = [x for x in z.infolist() if not x.is_dir()]
            assert len(members) == 1 and members[0].filename.endswith('.csv')
            with z.open(members[0]) as raw:
                for row in csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig', newline='')):
                    ts = int(row['open_time' if item['kind'] == 'markPriceKlines' else 'calc_time'])
                    if item['kind'] == 'markPriceKlines' and ts not in selected:
                        continue
                    assert ts not in found
                    found[ts] = row
        assert set(found) == set(selected)
        fields = ('open', 'high', 'low', 'close') if item['kind'] == 'markPriceKlines' else ('funding_interval_hours', 'last_funding_rate')
        for ts in found:
            for field in fields:
                assert math.isclose(float(found[ts][field]), float(selected[ts][field]), rel_tol=1e-10, abs_tol=1e-12)
        checks.append({'kind': item['kind'], 'contract': item['contract'], 'month': item['month'],
                       'cache_sha256': item['cache_sha256'], 'source_sha256': item['source_sha256'], 'rows': len(found)})
    result = {'all_checks_pass': True, 'local_cache_files_checked': len(checks),
              'local_rows_checked': sum(x['rows'] for x in checks), 'checks': checks,
              'fallbacks': [x for x in entries if 'local_fallback' in x],
              'journal_sha256': sha(journal) if journal.exists() else None,
              'plan_sha256': sha(H / '2024本地风险结算方案.md'),
              'settlement_code_sha256': sha(H / 'settle_2024_local_sources.py'), 'audit_code_sha256': sha(Path(__file__)),
              'note': 'Verifies new local caches against ZIPs; the independent ledger audit checks all verified trade paths.'}
    (H / '2024本地风险来源独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OBS62_2024_LOCAL_RISK_AUDIT', len(checks), 'rows', result['local_rows_checked'], flush=True)


if __name__ == '__main__':
    main()
