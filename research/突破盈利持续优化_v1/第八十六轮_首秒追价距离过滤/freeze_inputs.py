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
    sources = {
        'r79_freeze': P / '第七十九轮_完成周线趋势/冻结时点.json',
        'r81_freeze': P / '第八十一轮_八至十月一秒观察/冻结结果/冻结哈希.json',
        'r81_combined': P / '第八十一轮_八至十月一秒观察/四时段等名义合并.json',
        'r81_audit': P / '第八十一轮_八至十月一秒观察/四时段合并独立核验.json',
        'r82_freeze': P / '第八十二轮_八至十月持仓量过滤/冻结结果/冻结哈希.json',
        'r82_combined': P / '第八十二轮_八至十月持仓量过滤/四时段持仓量合并.json',
        'r82_audit': P / '第八十二轮_八至十月持仓量过滤/四时段持仓量合并独立核验.json',
        'r82_detail': P / '第八十二轮_八至十月持仓量过滤/持仓量过滤逐笔.csv'}
    for key in ('r81_audit', 'r82_audit'):
        assert json.loads(sources[key].read_text(encoding='utf-8'))['all_checks_pass']
    out = {'plan_sha256': sha(H / '冻结研究方案.md'), 'sources_sha256': {k: sha(v) for k, v in sources.items()},
           'source_paths': {k: str(v) for k, v in sources.items()}, 'frozen_utc': datetime.now(timezone.utc).isoformat(),
           'note': 'One causal 0.05% extension gate, frozen after seeing prior exploratory results.'}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT86_FREEZE', sha(target), flush=True)


if __name__ == '__main__':
    main()
