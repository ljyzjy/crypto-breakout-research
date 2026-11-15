"""Trace unrankable hours to invalid source-minute inputs, without imputing prices."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import replay_2022 as runner

H = Path(__file__).resolve().parent
sys.path.insert(0, str(H.parent / '第四十六轮_固定十一加密币跨时段'))
import prepare_fixed11_chunked as prep


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    runner.guard(start=True)
    quality_path = H / '二零二二候选准备质量.json'
    quality = json.loads(quality_path.read_text(encoding='utf-8'))
    supplementary = json.loads((H / '二零二二日档补源质量.json').read_text(encoding='utf-8'))
    expected = set(quality['unknown_rank_hours_ms']); missing = Counter(); invalid_hours = []
    sources = {x['symbol']: x for x in supplementary['selected_sources']}
    for meta in sorted((runner.ROOT / 'candidate_chunks').glob('*.json')):
        runner.guard()
        item = json.loads(meta.read_text(encoding='utf-8')); symbol = item['symbol']
        assert item['source_sha256'] == sources[symbol]['sha256']
        hourly = pd.read_parquet(item['hours_path'])
        indicators = prep.hourly_indicator()(hourly, '2021-12-01', '2023-01-01')
        z = indicators[indicators.decision_hour.isin(expected)]
        missing[symbol] += int((~(np.isfinite(z.score) & np.isfinite(z.rvol))).sum())
        bad = hourly[~hourly.valid]
        minute = pd.read_parquet(sources[symbol]['path'])
        for h in bad.itertuples(index=False):
            d = minute[minute.ts.between(int(h.open_time), int(h.open_time) + 3599999)]
            zero = d[(d.volume <= 0) | (d.quote_volume <= 0) | (d.trade_count <= 0)]
            assert len(d) == 60 and len(zero) > 0
            invalid_hours.append({'symbol': symbol, 'open_time_ms': int(h.open_time), 'zero_trade_minutes': len(zero)})
    raw = pd.read_parquet(H / '候选数据/固定十一币潜在分钟候选.parquet')
    count = int((raw.trigger_minute // 3600000 * 3600000).isin(expected).sum())
    assert len(expected) == 240 and count == 182
    out = {'all_checks_pass': True, 'unknown_rank_hours': len(expected),
           'unrankable_indicator_counts_by_symbol': dict(missing), 'invalid_hour_inputs': invalid_hours,
           'raw_potential_events_during_unknown_rank_hours': count,
           'quality_sha256': sha(quality_path), 'code_sha256': sha(Path(__file__)),
           'note': 'Zero-trade minutes are present in source records; fixed model marks their completed hour invalid and lookbacks propagate uncertainty. No imputation.'}
    (H / '未知排名小时来源诊断.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_UNKNOWN_HOURS', json.dumps({k: v for k, v in out.items() if k != 'invalid_hour_inputs'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
