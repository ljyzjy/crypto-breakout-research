import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
WORK = ROOT / 'work/oneobs81_aug_oct'
OLD = P / '第六十三轮_2026八至十月延伸'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    result = json.loads((H / '八至十月汇总独立核验.json').read_text(encoding='utf-8'))
    combined = json.loads((H / '四时段合并独立核验.json').read_text(encoding='utf-8'))
    progress = json.loads((H / '一秒逐笔回放进度.json').read_text(encoding='utf-8'))
    assert result['all_checks_pass'] and result['result_sha256'] == sha(H / '八至十月一秒观察结果.json')
    assert combined['all_checks_pass'] and combined['result_sha256'] == sha(H / '四时段等名义合并.json')
    assert progress['completed_groups'] == progress['total_groups'] == 53 and not progress['errors']
    target = H / '冻结结果'
    assert not target.exists()
    target.mkdir()
    names = ['冻结研究方案.md', '冻结时点.json', 'freeze_inputs.py', 'run_replay.py', 'build_batch.py', 'settle_risk.py',
             'audit_tapes.py', 'audit_risk.py', 'summarize.py', 'audit_summary.py', 'combine_periods.py', 'audit_combined.py',
             '一秒逐笔回放进度.json', '一秒逐笔独立样本核验.json', '风险来源与账本独立核验.json', '八至十月候选状态与账本.csv',
             '八至十月一秒观察结果.json', '八至十月汇总独立核验.json', '四时段已核验逐笔.csv', '四时段等名义合并.json',
             '四时段合并独立核验.json', '八至十月一秒观察回测结果.md']
    sources = {name: H / name for name in names}
    for p in (H / '一秒回放批次').glob('*'):
        if p.is_file(): sources['batch/' + p.name] = p
    for p in (OLD / '候选数据').glob('*.parquet'):
        sources['candidate_inputs/' + p.name] = p
    for name in ('延伸候选准备质量.json', '行情代码冻结哈希.json', '延伸候选独立核验总表.json', '延伸日小时排名独立核验.json', '延伸候选特征独立核验.json'):
        sources['candidate_inputs/' + name] = OLD / name
    checkpoints = list((WORK / 'tape').glob('*.json'))
    assert len(checkpoints) == 53
    for p in checkpoints: sources['checkpoints/' + p.name] = p
    risk_meta = json.loads((H / '一秒回放批次/风险来源与结算.json').read_text(encoding='utf-8'))
    for item in risk_meta['sources']:
        if item['status'] != 'verified':
            continue
        path = Path(item['cache_path'])
        assert sha(path) == item['cache_sha256']
        sources['risk_cache/' + path.name] = path
    for name, path in sources.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        assert sha(path) == sha(dest)
    manifest = {'all_checks_pass': True, 'files': {name: sha(target / name) for name in sorted(sources)},
                'freeze_code_sha256': sha(Path(__file__)),
                'note': 'Frozen retrospective unit evidence and checkpoints; not blind or shared account.'}
    (target / '冻结哈希.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_FREEZE', len(sources), sha(target / '冻结哈希.json'), flush=True)


if __name__ == '__main__':
    main()
