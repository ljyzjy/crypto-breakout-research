"""Freeze the already-observed three-sample pilot and provenance, before replay."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent
R90 = P / '第九十轮_二零二二公开行情'
R93 = P / '第九十三轮_原始逐笔抽样交叉核验'


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    result = H / '研究冻结.json'
    assert not result.exists(), 'plan already frozen'
    proof = json.loads((R93 / '原始逐笔独立核验.json').read_text(encoding='utf-8'))
    samples = json.loads((R93 / '原始聚合逐笔样本对照.json').read_text(encoding='utf-8'))
    assert proof['all_checks_pass'] and proof['samples_checked'] == 3 and len(samples['samples']) == 3
    assert proof['source_sha256'] == sha(R93 / '原始聚合逐笔样本对照.json')
    sources = [H / '研究方案.md', R93 / '原始逐笔独立核验.json', R93 / '原始聚合逐笔样本对照.json',
               R90 / '候选数据/固定十一币双币过滤潜在触价.parquet', R90 / '一秒逐笔独立样本核验.json',
               P / '第六十二轮_一秒观察更早突破/one_second_observation.py',
               P / '第六十二轮_一秒观察更早突破/audit_tape_samples.py',
               P / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py']
    raw = []
    for sample in samples['samples']:
        for meta in sample['raw_archives']:
            path = Path(r'D:\CodexResearch_2022_firstsec_20261115_v1\independent_raw_trade_samples') / f"{sample['contract']}-trades-{meta['day']}.zip"
            assert sha(path) == meta['sha256']
            raw.append({'path': str(path), 'sha256': meta['sha256']})
    out = {'frozen_utc': datetime.now(timezone.utc).isoformat(), 'plan_sha256': sha(H / '研究方案.md'),
           'sample_ids': [s['observation_id'] for s in samples['samples']], 'raw_archives': raw,
           'sources': {str(p): sha(p) for p in sources},
           'note': 'Sample outcomes were already partly observed. This is a non-random technical pilot, not a blind or profitability test.'}
    result.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT97_PLAN_FROZEN', len(out['sample_ids']))


if __name__ == '__main__': main()
