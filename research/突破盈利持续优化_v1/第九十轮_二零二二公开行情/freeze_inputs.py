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
    dest = H / '冻结时点.json'
    assert not dest.exists()
    files = {'candidate_generator': P / '第六十三轮_2026八至十月延伸/准备延伸候选.py',
             'chunk_engine': P / '第四十六轮_固定十一加密币跨时段/chunk_exact.py',
             'minute_engine': P / '第四十六轮_固定十一加密币跨时段/minute_features_chunked.py',
             'preparation': P / '第四十六轮_固定十一加密币跨时段/prepare_fixed11_chunked.py',
             'market_gate': P / '第四十轮_BTC_ETH事前活跃度/market_decisions.py',
             'one_second': P / '第六十二轮_一秒观察更早突破/one_second_observation.py',
             'risk_engine': P / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py',
             'price_distance': P / '第八十六轮_首秒追价距离过滤/extension_gate.py',
             'extended_exit': P / '第八十八轮_延长一根柱持有/extend_exit.py',
             'stream_reader': P / '第四十七轮_一次重新突破确认/public_tape_stream.py',
             'range_reader': P / '第四十八轮_固定一倍风险止盈/public_range.py'}
    out = {'plan_sha256': sha(H / '冻结研究方案.md'), 'source_paths': {k: str(v) for k, v in files.items()},
           'source_sha256': {k: sha(v) for k, v in files.items()},
           'data_root': r'D:\CodexResearch_2022_firstsec_20261115_v1',
           'warmup_utc': '2021-12-01', 'begin_utc': '2022-01-01', 'end_utc_exclusive': '2023-01-01',
           'frozen_utc': datetime.now(timezone.utc).isoformat(),
           'note': 'Fixed before downloading 2022 data; later-selected coin universe is survivorship biased.'}
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_FREEZE', sha(dest), flush=True)


if __name__ == '__main__':
    main()
