import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
WORK = ROOT / 'work/oneobs88_extend'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    final = json.loads((H / '延长持有配对独立核验.json').read_text(encoding='utf-8'))
    risk = json.loads((H / '延长持有风险独立核验.json').read_text(encoding='utf-8'))
    progress = json.loads((H / '延长持有逐笔进度.json').read_text(encoding='utf-8'))
    assert final['all_checks_pass'] and final['result_sha256'] == sha(H / '延长持有配对汇总.json')
    assert risk['all_checks_pass'] and risk['source_sha256'] == sha(H / '延长持有风险账本.json')
    assert progress['completed_groups'] == progress['total_groups'] == 34 and not progress['errors']
    dest = H / '冻结结果'
    assert not dest.exists()
    dest.mkdir()
    names = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'extend_exit.py', 'test_extend_exit.py', '延长持有合成核验.json',
             'build_replay_inputs.py', '原柱末退出回放输入.json', 'run_extension.py', '延长持有逐笔进度.json',
             'settle_extension.py', 'audit_tape_samples.py', '延长持有逐笔独立核验.json', 'audit_risk.py',
             '延长持有风险账本.json', '延长持有风险独立核验.json', 'summarize_paired.py', 'audit_paired.py',
             '延长持有配对逐笔.csv', '延长持有配对汇总.json', '延长持有配对独立核验.json', '延长持有配对结果.md']
    sources = {name: H / name for name in names}
    checkpoints = list((WORK / 'tape').glob('*.json'))
    assert len(checkpoints) == 34
    for p in checkpoints: sources['checkpoints/' + p.name] = p
    ledger = json.loads((H / '延长持有风险账本.json').read_text(encoding='utf-8'))
    for x in ledger['risk_archives']:
        if x['status'] != 'verified':
            continue
        cache = Path(x['cache_path'])
        assert sha(cache) == x['cache_sha256']
        sources['risk_cache/' + cache.name] = cache
    for name, path in sources.items():
        target = dest / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        assert sha(path) == sha(target)
    out = {'all_checks_pass': True, 'files': {name: sha(dest / name) for name in sorted(sources)},
           'freeze_code_sha256': sha(Path(__file__)), 'note': 'Historical paired exit research; not blind, live, or account validation.'}
    (dest / '冻结哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT88_FREEZE', len(sources), sha(dest / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
