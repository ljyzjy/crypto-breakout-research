import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    a = json.loads((H / '延长钱包独立核验.json').read_text(encoding='utf-8'))
    b = json.loads((H / '延长钱包风险预算核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['result_sha256'] == sha(H / '延长钱包情景汇总.json')
    assert b['all_checks_pass'] and b['wallet_audit_sha256'] == sha(H / '延长钱包独立核验.json')
    names = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'run_hold_wallet.py', 'audit_hold_wallet.py',
             'audit_risk_budget.py', '延长钱包情景逐笔.csv', '延长钱包事件账本.csv', '延长钱包情景汇总.json',
             '延长钱包独立核验.json', '延长钱包风险预算核验.json', '延长持有共享钱包结果.md']
    dest = H / '冻结结果'
    assert not dest.exists()
    dest.mkdir()
    for name in names:
        shutil.copy2(H / name, dest / name)
        assert sha(H / name) == sha(dest / name)
    out = {'all_checks_pass': True, 'files': {name: sha(dest / name) for name in names},
           'freeze_code_sha256': sha(Path(__file__)),
           'note': 'Known-path conditional wallet, unknowns omitted; no floating-equity or real execution validation.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT89_FREEZE', len(names), sha(dest / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
