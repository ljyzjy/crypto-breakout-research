import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    a = json.loads((H / '首秒距离钱包独立核验.json').read_text(encoding='utf-8'))
    b = json.loads((H / '首秒距离风险预算核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['result_sha256'] == sha(H / '首秒距离钱包情景汇总.json')
    assert b['all_checks_pass'] and b['wallet_audit_sha256'] == sha(H / '首秒距离钱包独立核验.json')
    files = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'run_extension_wallet.py', 'audit_extension_wallet.py',
             'audit_risk_budget.py', '首秒距离钱包情景逐笔.csv', '首秒距离钱包事件账本.csv', '首秒距离钱包情景汇总.json',
             '首秒距离钱包独立核验.json', '首秒距离风险预算核验.json', '首秒距离共享钱包结果.md']
    dest = H / '冻结结果'
    assert not dest.exists()
    dest.mkdir()
    for name in files:
        shutil.copy2(H / name, dest / name)
        assert sha(H / name) == sha(dest / name)
    out = {'all_checks_pass': True, 'files': {name: sha(dest / name) for name in files},
           'freeze_code_sha256': sha(Path(__file__)),
           'note': 'Known paths only; unresolved candidates omitted and unrealized PnL not included in wallet drawdown.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT87_FREEZE', len(files), sha(dest / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
