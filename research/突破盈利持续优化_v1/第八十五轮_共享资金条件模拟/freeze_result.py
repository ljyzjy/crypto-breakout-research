import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    a = json.loads((H / '共享钱包独立核验.json').read_text(encoding='utf-8'))
    b = json.loads((H / '风险预算超限独立核验.json').read_text(encoding='utf-8'))
    assert a['all_checks_pass'] and a['result_sha256'] == sha(H / '共享钱包情景汇总.json')
    assert b['all_checks_pass'] and b['result_sha256'] == sha(H / '风险预算超限统计.json')
    files = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'wallet_simulator.py', 'test_wallet_simulator.py',
             '钱包时序合成核验.json', 'run_wallet.py', 'audit_wallet.py', 'summarize_budget_breaches.py',
             'audit_budget_breaches.py', '共享钱包情景逐笔.csv', '共享钱包事件账本.csv', '共享钱包情景汇总.json',
             '共享钱包独立核验.json', '风险预算超限统计.json', '风险预算超限独立核验.json', '已知路径共享钱包情景.md']
    dest = H / '冻结结果'
    assert not dest.exists()
    dest.mkdir()
    for name in files:
        shutil.copy2(H / name, dest / name)
        assert sha(H / name) == sha(dest / name)
    out = {'all_checks_pass': True, 'files': {name: sha(dest / name) for name in files},
           'freeze_code_sha256': sha(Path(__file__)),
           'note': 'Known-path-only wallet simulation, unknowns omitted, realized-wallet drawdown only.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT85_FREEZE', len(files), sha(dest / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
