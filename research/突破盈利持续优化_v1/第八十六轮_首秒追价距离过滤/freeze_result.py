import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((H / '首秒距离独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['result_sha256'] == sha(H / '首秒距离跨期对照.json')
    files = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'extension_gate.py', 'test_extension_gate.py',
             '追价距离合成核验.json', 'evaluate_extension.py', 'audit_extension.py', '首秒距离逐笔.csv',
             '首秒距离跨期对照.json', '首秒距离独立核验.json', '限制首秒追价距离结果.md']
    dest = H / '冻结结果'
    assert not dest.exists()
    dest.mkdir()
    for name in files:
        shutil.copy2(H / name, dest / name)
        assert sha(H / name) == sha(dest / name)
    out = {'all_checks_pass': True, 'files': {name: sha(dest / name) for name in files},
           'freeze_code_sha256': sha(Path(__file__)), 'note': 'Single post-hoc-period gate; historical exploration, no account proof.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT86_FREEZE', len(files), sha(dest / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
