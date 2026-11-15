"""Freeze a year's independently audited stronger-flow comparison."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main(year):
    result = H / f'{year}强方向对照.json'
    audit = json.loads((H / f'{year}强方向独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['groups_checked'] == 24 and audit['result_sha256'] == sha(result)
    names = ['冻结研究方案.md', '冻结时点.json', 'evaluate_strong_flow.py', 'audit_strong_flow.py',
             'freeze_strong_flow.py', f'{year}强方向逐笔.csv', result.name, f'{year}强方向独立核验.json']
    dest = H / f'{year}冻结结果'
    dest.mkdir(exist_ok=True)
    files = {}
    for name in names:
        source, target = H / name, dest / name
        digest = sha(source)
        if target.exists():
            assert sha(target) == digest
        else:
            shutil.copyfile(source, target)
            assert sha(target) == digest
        files[name] = digest
    out = {'all_checks_pass': True, 'year': year, 'files': files,
           'note': 'Exploratory fixed-threshold historical comparison, not independent OOS or account results.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('STRONG_FLOW_FREEZE', year, len(files), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
