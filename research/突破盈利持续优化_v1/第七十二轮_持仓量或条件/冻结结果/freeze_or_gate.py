"""Freeze the audited OR-gate historical comparison."""
import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((H / '或条件独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['groups_checked'] == 48
    assert audit['result_sha256'] == sha(H / '或条件跨期对照.json')
    names = ['冻结研究方案.md', '冻结时点.json', 'evaluate_or_gate.py', '或条件跨期对照.json',
             '或条件逐笔明细.csv', 'audit_or_gate.py', '或条件独立核验.json', 'freeze_or_gate.py']
    dest = H / '冻结结果'
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
    out = {'all_checks_pass': True, 'files': files, 'historical_exploration': True,
           'note': 'Input snapshots preserved separately; no shared-account or live validation.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OI_OR_FREEZE', len(files), flush=True)


if __name__ == '__main__':
    main()
