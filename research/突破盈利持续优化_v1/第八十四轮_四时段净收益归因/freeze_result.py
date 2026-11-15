import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    a = json.loads((H / '成本归因独立核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['result_sha256'] == sha(H / '四时段成本归因.json')
    files = ['研究口径.md', 'attribute_cost.py', 'audit_cost.py', '四时段成本归因逐笔.csv',
             '四时段成本归因.json', '成本归因独立核验.json', '为什么一秒突破仍未盈利.md']
    dest = H / '冻结结果'
    assert not dest.exists()
    dest.mkdir()
    for name in files:
        shutil.copy2(H / name, dest / name)
        assert sha(H / name) == sha(dest / name)
    out = {'all_checks_pass': True, 'files': {name: sha(dest / name) for name in files},
           'freeze_code_sha256': sha(Path(__file__)), 'note': 'Historical unit-cost attribution, not a prospective signal.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT84_FREEZE', len(files), sha(dest / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
