"""Freeze the independently checked 2023 one-second-observation baseline."""
import hashlib
import json
from pathlib import Path
import shutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
R62 = P / '第六十二轮_一秒观察更早突破'
B = R62 / '2023一秒观察分批'
DEST = H / '2023基础冻结结果'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    frozen = read(H / '冻结时点.json')
    progress = read(R62 / '2023一秒观察逐笔进度.json')
    assert progress['processed_groups'] == progress['total_groups'] == frozen['known_groups'] == 119
    assert progress['original_unknown'] == 19 and not progress['errors'] and progress['fingerprint'] == frozen['runner_fingerprint']
    quality = read(B / '动态池逐笔提取质量.json')
    assert quality['candidate_events'] == 146
    samples = read(R62 / '2023一秒观察逐笔独立核验.json')
    ledger = read(R62 / '2023一秒观察账本独立核验.json')
    summary = read(R62 / '2023一秒观察对照.json')
    assert samples['all_checks_pass'] and len(samples['samples']) >= 3 and ledger['all_checks_pass']
    assert len(summary['rows']) == 2 and all(r['candidate_events'] == 146 and r['one_second_observation']['unknown'] >= 19 for r in summary['rows'])
    journal = [json.loads(x) for x in (H / '2023续跑记录.jsonl').read_text(encoding='utf-8').splitlines()]
    assert journal[-1]['event'] == 'end'
    selected = []
    for name in ['动态池逐笔信号筛查.parquet', '动态池延迟市价路径.parquet', '动态池逐笔提取质量.json',
                 '逐笔执行冻结方案.json', '动态池单位收益与风险.parquet', '动态池单位筛查完整性.json', '动态池风险档案核验清单.json']:
        selected.append((B / name, Path('batch') / name))
    for name in ['冻结研究方案.md', 'run_observation.py', 'one_second_observation.py', '2023输入冻结哈希.json',
                 '2023已知候选逐笔来源.json', '2023一秒观察逐笔进度.json', '2023一秒观察对照.json',
                 '2023一秒观察已核验机会.parquet', '2023一秒观察逐笔独立核验.json', '2023一秒观察账本独立核验.json']:
        selected.append((R62 / name, Path('support') / name))
    for name in ['冻结研究方案.md', '冻结时点.json', 'run_2023_adaptive.py', '2023续跑记录.jsonl', 'settle_2023_guarded.py', 'freeze_2023_baseline.py']:
        selected.append((H / name, Path('extension') / name))
    for path in (R62 / '2023冻结输入').rglob('*'):
        if path.is_file():
            selected.append((path, Path('input') / path.relative_to(R62 / '2023冻结输入')))
    cps = list((ROOT / 'work/oneobs62_2023/tape').glob('*.json'))
    assert len(cps) == 119
    selected += [(p, Path('checkpoints') / p.name) for p in cps]
    files = {}
    for source, rel in selected:
        target = DEST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = sha(source)
        if target.exists():
            assert sha(target) == digest
        else:
            shutil.copyfile(source, target)
            assert sha(target) == digest
        files[str(rel).replace('\\', '/')] = digest
    out = {'all_checks_pass': True, 'year': '2023', 'known_groups': len(cps), 'original_unknown': 19,
           'risk_paths_checked': ledger['audited_one_second_observation_paths'], 'sample_replays': len(samples['samples']),
           'files': files, 'note': 'Exploratory historical unit paths; no live execution or account simulation.'}
    (DEST / '完整快照哈希.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('YEAR2023_BASE_FREEZE', len(files), flush=True)


if __name__ == '__main__':
    main()
