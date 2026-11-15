import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
OLD = P / '第六十三轮_2026八至十月延伸'
R62 = P / '第六十二轮_一秒观察更早突破'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    target = H / '冻结时点.json'
    assert not target.exists()
    q = json.loads((OLD / '延伸候选准备质量.json').read_text(encoding='utf-8'))
    assert q['period_utc'] == ['2026-08-01', '2026-11-01'] and q['post_hour_and_market_candidates'] == 57
    for name, value in q['outputs_sha256'].items():
        assert sha(OLD / '候选数据' / name) == value
    assert q['sources_sha256'] == sha(OLD / '行情代码冻结哈希.json')
    candidates = pq.read_table(OLD / '候选数据/固定十一币双币过滤潜在触价.parquet').to_pylist()
    assert len(candidates) == len({x['observation_id'] for x in candidates}) == 57
    hashes = {'plan_sha256': sha(H / '冻结研究方案.md'),
              'candidate_quality_sha256': sha(OLD / '延伸候选准备质量.json'),
              'candidate_sha256': sha(OLD / '候选数据/固定十一币双币过滤潜在触价.parquet'),
              'source_sha256': sha(OLD / '行情代码冻结哈希.json'),
              'one_second_plan_sha256': sha(R62 / '冻结研究方案.md'),
              'one_second_engine_sha256': sha(R62 / 'one_second_observation.py'),
              'one_second_tests_sha256': sha(R62 / '一秒观察合成时序核验.json'),
              'frozen_utc': datetime.now(timezone.utc).isoformat(), 'candidate_count': len(candidates),
              'note': 'Prior full project has viewed this period; no project-level blind sample.'}
    target.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_FROZEN', sha(target), 'candidate_count', len(candidates), flush=True)


if __name__ == '__main__':
    main()
