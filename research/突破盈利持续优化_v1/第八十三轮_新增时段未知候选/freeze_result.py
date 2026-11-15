import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    b = json.loads((H / 'BNB独立核验.json').read_text(encoding='utf-8'))
    s = json.loads((H / '修复敏感性独立核验.json').read_text(encoding='utf-8'))
    assert b['all_checks_pass'] and b['source_result_sha256'] == sha(H / '三个候选来源复核.json')
    assert s['all_checks_pass'] and s['result_sha256'] == sha(H / '两次数据修复敏感性.json')
    files = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'reconcile_three.py', 'audit_bnb.py',
             'diagnose_sol.py', 'combined_sensitivity.py', 'audit_sensitivity.py', '三个候选来源复核.json',
             'BNB独立核验.json', 'SOL路径分歧诊断.json', '两次数据修复敏感性.json', '修复敏感性独立核验.json',
             '三个未知候选核验结果.md']
    dest = H / '冻结结果'
    assert not dest.exists()
    dest.mkdir()
    for name in files:
        shutil.copy2(H / name, dest / name)
        assert sha(H / name) == sha(dest / name)
    out = {'all_checks_pass': True, 'files': {name: sha(dest / name) for name in files},
           'freeze_code_sha256': sha(Path(__file__)), 'note': 'Retrospective source-repair sensitivities; no original ledger was changed.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT83_FREEZE', len(files), sha(dest / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
