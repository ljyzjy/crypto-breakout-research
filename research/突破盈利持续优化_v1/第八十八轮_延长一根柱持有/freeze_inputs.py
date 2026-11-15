import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

H = Path(__file__).resolve().parent
P = H.parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    target = H / '冻结时点.json'
    assert not target.exists()
    sources = {'r79': P / '第七十九轮_完成周线趋势/冻结时点.json',
               'r81_snapshot': P / '第八十一轮_八至十月一秒观察/冻结结果/冻结哈希.json',
               'r81_combined': P / '第八十一轮_八至十月一秒观察/四时段等名义合并.json',
               'r81_audit': P / '第八十一轮_八至十月一秒观察/四时段合并独立核验.json',
               'r82_snapshot': P / '第八十二轮_八至十月持仓量过滤/冻结结果/冻结哈希.json',
               'r86_snapshot': P / '第八十六轮_首秒追价距离过滤/冻结结果/冻结哈希.json',
               'r86_detail': P / '第八十六轮_首秒追价距离过滤/首秒距离逐笔.csv',
               'r86_audit': P / '第八十六轮_首秒追价距离过滤/首秒距离独立核验.json',
               'r62_engine': P / '第六十二轮_一秒观察更早突破/one_second_observation.py',
               'risk_engine': P / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py',
               'range_reader': P / '第四十八轮_固定一倍风险止盈/public_range.py',
               'stream_reader': P / '第四十七轮_一次重新突破确认/public_tape_stream.py'}
    for name in ('r81_audit', 'r86_audit'):
        assert json.loads(sources[name].read_text(encoding='utf-8'))['all_checks_pass']
    out = {'plan_sha256': sha(H / '冻结研究方案.md'), 'source_paths': {k: str(v) for k, v in sources.items()},
           'sources_sha256': {k: sha(v) for k, v in sources.items()}, 'frozen_utc': datetime.now(timezone.utc).isoformat(),
           'note': 'One fixed additional 15-minute holding window after prior historical results; not independent blind.'}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT88_FREEZE', sha(target), flush=True)


if __name__ == '__main__':
    main()
