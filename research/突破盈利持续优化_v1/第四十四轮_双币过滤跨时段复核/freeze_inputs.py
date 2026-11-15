"""Freeze both retrospective slices and original untouched source files."""
import hashlib, json, shutil
from pathlib import Path
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
I = H / '冻结输入'
I.mkdir(exist_ok=True)
A = P / '第三十三轮_动态池逐笔执行'
B = P / '第三十四轮_历史候选动态替补'
sources = {
    'original_signal.parquet': A/'动态池逐笔信号筛查.parquet',
    'original_paths.parquet': A/'动态池延迟市价路径.parquet',
    'original_quality.json': A/'动态池逐笔提取质量.json',
    'original_plan.json': A/'逐笔执行冻结方案.json',
    'backup_candidates.parquet': B/'替补动态池潜在触价_待逐笔验证.parquet',
    'backup_signal.parquet': B/'替补新增逐笔信号.parquet',
    'backup_paths.parquet': B/'替补新增延迟市价路径.parquet',
    'backup_quality.json': B/'替补新增逐笔质量.json',
    'backup_plan.json': B/'替补逐笔执行冻结方案.json',
    'shared_audit.json': B/'共同候选复用独立核验.json',
}
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    target = H/'输入冻结哈希.json'
    if target.exists():
        old = json.loads(target.read_text(encoding='utf-8'))
        assert old['plan_sha256'] == sha(H/'冻结研究方案.md')
        for name, digest in old['inputs'].items(): assert sha(I/name) == digest
        print('CROSS44_ALREADY_FROZEN', len(old['inputs']), flush=True)
        return
    for name, source in sources.items():
        dest = I/name
        if dest.exists(): assert sha(dest) == sha(source)
        else: shutil.copy2(source, dest)
        assert sha(dest) == sha(source)
    audit = json.loads((I/'shared_audit.json').read_text(encoding='utf-8'))
    assert audit['all_signal_and_rules_match']
    candidate = pd.read_parquet(I/'backup_candidates.parquet')
    signals = pd.concat([pd.read_parquet(I/'original_signal.parquet'), pd.read_parquet(I/'backup_signal.parquet')], ignore_index=True)
    paths = pd.concat([pd.read_parquet(I/'original_paths.parquet'), pd.read_parquet(I/'backup_paths.parquet')], ignore_index=True)
    assert candidate.observation_id.is_unique and signals.observation_id.is_unique
    assert not paths.duplicated(['observation_id','variant']).any()
    assert set(candidate.observation_id) == set(signals.observation_id)
    # Preserve all source anomalies as unknown; this batch does not substitute raw-source resolutions.
    def ts(x): return int(pd.Timestamp(x, tz='UTC').timestamp()*1000)
    windows = [('2024_may_jun',ts('2024-05-01 01:00'),ts('2024-07-01')),
               ('2026_may_jul',ts('2026-05-01'),ts('2026-08-01'))]
    pieces=[]
    for tag, lo, hi in windows:
        ids = set(candidate.loc[(candidate.trigger_minute>=lo)&(candidate.quarter_end+60_000<=hi),'observation_id'])
        x = signals[signals.observation_id.isin(ids)].copy()
        assert len(x) == len(ids)
        x['research_period'] = tag
        pieces.append(x)
    result = pd.concat(pieces, ignore_index=True)
    assert result.observation_id.is_unique
    paths = paths[paths.observation_id.isin(result.observation_id)].copy()
    result.to_parquet(I/'baseline_signal.parquet', index=False)
    paths.to_parquet(I/'baseline_paths.parquet', index=False)
    frozen = {'plan_sha256':sha(H/'冻结研究方案.md'),
              'inputs':{name:sha(I/name) for name in [*sources,'baseline_signal.parquet','baseline_paths.parquet']},
              'windows_utc':windows,
              'note':'Original source discrepancies retained; no outcomes or parameters used to choose the periods.'}
    target.write_text(json.dumps(frozen,ensure_ascii=False,indent=2), encoding='utf-8')
    print('CROSS44_INPUTS_FROZEN', len(result), 'candidates',len(paths),'paths',flush=True)
if __name__=='__main__': main()
