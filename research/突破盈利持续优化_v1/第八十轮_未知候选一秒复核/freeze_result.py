import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((H / '单例一秒独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '单例一秒复核结果.json')
    assert audit['audit_code_sha256'] == sha(H / 'audit_xrp.py')
    names = ['冻结方案.md', '冻结时点.json', 'one_second_check.py', 'test_one_second_check.py',
             '首秒边界测试.json', 'freeze_inputs.py', 'recheck_xrp.py', 'audit_xrp.py',
             '单例一秒复核结果.json', '单例一秒独立核验.json', '单例未知候选复核结果.md']
    target = H / '冻结结果'
    assert not target.exists()
    target.mkdir()
    for name in names:
        shutil.copy2(H / name, target / name)
        assert sha(H / name) == sha(target / name)
    manifest = {'all_checks_pass': True, 'files': {name: sha(target / name) for name in names},
                'freeze_code_sha256': sha(Path(__file__)), 'note': 'Retrospective one-case source sensitivity.'}
    (target / '冻结哈希.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('XRP_FREEZE', len(names), sha(target / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
