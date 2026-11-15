"""Freeze a completed and independently audited 1R paired batch."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main(year):
    progress = json.loads((H / f'{year}一倍止盈逐笔进度.json').read_text(encoding='utf-8'))
    risk = json.loads((H / f'{year}一倍止盈本地风险账本.json').read_text(encoding='utf-8'))
    tape = json.loads((H / f'{year}一倍止盈逐笔独立核验.json').read_text(encoding='utf-8'))
    ledger = json.loads((H / f'{year}一倍止盈账本独立核验.json').read_text(encoding='utf-8'))
    summary = json.loads((H / f'{year}一倍止盈汇总独立核验.json').read_text(encoding='utf-8'))
    assert progress['attempted_groups'] == progress['total_groups'] and not progress['errors']
    assert risk['replay_fingerprint'] == progress['fingerprint'] and tape['replay_fingerprint'] == progress['fingerprint']
    assert tape['all_checks_pass'] and len(tape['samples']) >= 3 and ledger['all_checks_pass'] and summary['all_checks_pass']
    assert ledger['ledger_sha256'] == sha(H / f'{year}一倍止盈本地风险账本.json')
    assert summary['result_sha256'] == sha(H / f'{year}一倍止盈配对对照.json')
    cps = list((ROOT / 'work' / f'oneobs1r70_{year}' / 'tape').glob('*.json'))
    assert len(cps) == progress['total_groups']
    for cp in cps:
        x = json.loads(cp.read_text(encoding='utf-8'))
        assert x['fingerprint'] == progress['fingerprint'] and x['status'] == 'verified'
    names = ['冻结研究方案.md', '冻结时点.json', 'exit_1r_oneobs.py', 'test_exit_1r_oneobs.py', '一秒观察一倍止盈合成核验.json',
             'replay_1r.py', 'settle_1r_local.py', 'audit_1r_tapes.py', 'audit_1r_ledger.py', 'test_audit_1r_ledger.py',
             '一倍止盈账本核验合成测试.json', 'describe_1r.py', 'audit_1r_summary.py', 'freeze_1r.py',
             f'{year}一倍止盈逐笔进度.json', f'{year}一倍止盈本地风险账本.json', f'{year}一倍止盈逐笔独立核验.json',
             f'{year}一倍止盈账本独立核验.json', f'{year}一倍止盈配对对照.json', f'{year}一倍止盈汇总独立核验.json']
    selected = [(H / name, Path('support') / name) for name in names] + [(cp, Path('checkpoints') / cp.name) for cp in cps]
    dest = H / f'{year}一倍止盈冻结结果'
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
    result = {'all_checks_pass': True, 'year': year, 'groups': len(cps), 'paths_audited': ledger['audited_paths'],
              'tape_samples': len(tape['samples']), 'source_snapshot_sha256': risk['source_snapshot_sha256'],
              'replay_fingerprint': progress['fingerprint'], 'files': files,
              'note': 'Historical matched-entry comparison; missing candidates are not resolved or actual orders.'}
    (dest / '冻结哈希.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_1R_FREEZE', year, len(files), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2024', '2026')
    main(sys.argv[1])
