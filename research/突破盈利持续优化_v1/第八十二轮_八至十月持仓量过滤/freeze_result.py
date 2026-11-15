import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    a = json.loads((H / '持仓量过滤独立核验.json').read_text(encoding='utf-8'))
    b = json.loads((H / '四时段持仓量合并独立核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['result_sha256'] == sha(H / '持仓量过滤对照.json')
    assert b['all_checks_pass'] and b['result_sha256'] == sha(H / '四时段持仓量合并.json')
    names = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'prepare_oi.py', 'audit_oi.py', 'evaluate_oi.py',
             'audit_evaluation.py', 'combine_oi.py', 'audit_combined_oi.py', '持仓量逐点来源核验.json',
             '持仓量逐点独立核验.json', '持仓量过滤逐笔.csv', '持仓量过滤对照.json', '持仓量过滤独立核验.json',
             '四时段持仓量已核验逐笔.csv', '四时段持仓量合并.json', '四时段持仓量合并独立核验.json', '八至十月持仓量过滤结果.md']
    target = H / '冻结结果'
    assert not target.exists()
    target.mkdir()
    for name in names:
        shutil.copy2(H / name, target / name)
        assert sha(H / name) == sha(target / name)
    out = {'all_checks_pass': True, 'files': {name: sha(target / name) for name in names},
           'freeze_code_sha256': sha(Path(__file__)), 'note': 'Post-hoc historical OI evidence, not blind or an account.'}
    (target / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT82_FREEZE', len(names), sha(target / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
