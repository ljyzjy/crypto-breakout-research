"""Freeze one audited matched-entry 3R comparison."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main(year):
    progress = json.loads((H / f'{year}三倍止盈逐笔进度.json').read_text(encoding='utf-8'))
    risk = json.loads((H / f'{year}三倍止盈风险账本.json').read_text(encoding='utf-8'))
    tape = json.loads((H / f'{year}三倍止盈逐笔独立核验.json').read_text(encoding='utf-8'))
    ledger = json.loads((H / f'{year}三倍止盈账本独立核验.json').read_text(encoding='utf-8'))
    summary = json.loads((H / f'{year}三倍止盈汇总独立核验.json').read_text(encoding='utf-8'))
    assert progress['attempted_groups'] == progress['total_groups'] and not progress['errors']
    assert progress['fingerprint'] == risk['replay_fingerprint'] == tape['replay_fingerprint']
    assert tape['all_checks_pass'] and len(tape['samples']) >= min(3, progress['total_groups']) and ledger['all_checks_pass'] and summary['all_checks_pass']
    assert ledger['ledger_sha256'] == sha(H / f'{year}三倍止盈风险账本.json') and summary['result_sha256'] == sha(H / f'{year}三倍止盈配对对照.json')
    cps = list((ROOT / 'work' / f'oneobs3r78_{year}' / 'tape').glob('*.json'))
    assert len(cps) == progress['total_groups']
    for cp in cps:
        x = json.loads(cp.read_text(encoding='utf-8'))
        assert x['fingerprint'] == progress['fingerprint'] and x['status'] == 'verified'
    names = ['冻结研究方案.md', '冻结时点.json', 'exit_3r.py', 'test_exit_3r.py', '三倍止盈合成核验.json',
             'replay_3r_targets.py', 'settle_3r.py', 'audit_3r_tapes.py', 'audit_3r_ledger.py',
             'describe_3r.py', 'audit_3r_summary.py', 'freeze_3r.py',
             f'{year}三倍止盈逐笔进度.json', f'{year}三倍止盈风险账本.json', f'{year}三倍止盈逐笔独立核验.json',
             f'{year}三倍止盈账本独立核验.json', f'{year}三倍止盈配对逐笔.csv', f'{year}三倍止盈配对对照.json', f'{year}三倍止盈汇总独立核验.json']
    selected = [(H / name, Path('support') / name) for name in names] + [(cp, Path('checkpoints') / cp.name) for cp in cps]
    dependencies = [P / '第七十轮_一秒观察一倍止盈/settle_1r_local.py',
                    P / '第四十四轮_双币过滤跨时段复核/settle_cross_engine.py']
    if year == '2023':
        dependencies += [P / '第四十三轮_旧十一币2023年复核/settle_local_2023_serial.py',
                         P / '第四十三轮_旧十一币2023年复核/settle_2023_serial_engine.py',
                         P / '第四十三轮_旧十一币2023年复核/风险来源冻结哈希.json']
    dest = H / f'{year}冻结结果'
    files = {}
    for source, rel in selected:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = sha(source)
        if target.exists():
            assert sha(target) == digest
        else:
            shutil.copyfile(source, target)
            assert sha(target) == digest
        files[str(rel).replace('\\', '/')] = digest
    out = {'all_checks_pass': True, 'year': year, 'groups_replayed': len(cps), 'risk_paths_checked': ledger['audited_paths'],
           'reused_paths': ledger['reused_paths'], 'tape_samples': len(tape['samples']),
           'source_snapshot_sha256': risk['source_snapshot_sha256'], 'files': files,
           'dependency_sha256': {str(x): sha(x) for x in dependencies},
           'note': 'Historical matched units, not an account return or independent blind validation.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('THREE_R_FREEZE', year, len(files), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
