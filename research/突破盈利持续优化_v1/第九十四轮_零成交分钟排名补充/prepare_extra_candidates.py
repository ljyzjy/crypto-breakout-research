"""Generate only additional candidates in previously unrankable 2022 hours."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R90 = P / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
sys.path.insert(0, str(P / '第四十六轮_固定十一加密币跨时段')); import prepare_fixed11_chunked as prep
sys.path.insert(0, str(P / '第四十轮_BTC_ETH事前活跃度')); from market_decisions import classify


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    runner.guard(start=True)
    check = json.loads((H / '零成交小时来源核对.json').read_text(encoding='utf-8'))
    assert check['process_complete'] and check['code_sha256'] == sha(H / 'verify_zero_hours.py')
    assert check['frozen_sha256'] == sha(H / '冻结时点.json')
    audit = json.loads((H / '零成交小时独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['source_sha256'] == sha(H / '零成交小时来源核对.json')
    assert audit['code_sha256'] == sha(H / 'audit_zero_hours.py')
    for x in check['hourly_sources']:
        assert sha(Path(x['path'])) == x['sha256'] and sha(Path(x['original_hour_path'])) == x['original_hour_sha256']
    q90 = json.loads((R90 / '二零二二候选准备质量.json').read_text(encoding='utf-8'))
    for name, digest in q90['outputs_sha256'].items(): assert sha(R90 / '候选数据' / name) == digest
    old_unknown = set(q90['unknown_rank_hours_ms'])
    daily = pd.read_parquet(R90 / '候选数据/固定十一币历史日排名.parquet')
    indicator = prep.hourly_indicator(); features = []
    for x in check['hourly_sources']:
        g = indicator(pd.read_parquet(x['path']), '2021-12-01', '2023-01-01'); g['symbol'] = x['symbol']; features.append(g)
    feature = pd.concat(features, ignore_index=True)
    feature['day'] = pd.to_datetime(feature.decision_hour, unit='ms', utc=True).dt.strftime('%Y-%m-%d')
    merged = daily[['day', 'symbol', 'liquidity_rank']].merge(feature, on=['day', 'symbol'], how='left', validate='one_to_many')
    assert len(merged) == 24 * len(daily)
    merged['valid_feature'] = np.isfinite(merged.score) & np.isfinite(merged.rvol)
    merged['valid_count'] = merged.groupby('decision_hour').valid_feature.transform('sum')
    complete = merged[merged.valid_count.eq(11)]
    eligible = complete[complete.valid_feature & complete.rvol.ge(1.5) & complete.score.ne(0)].copy()
    eligible['side'] = np.where(eligible.score > 0, 1, -1); eligible['strength'] = eligible.score.abs()
    eligible = eligible.sort_values(['decision_hour', 'side', 'strength', 'liquidity_rank', 'symbol'], ascending=[True, True, False, True, True])
    eligible['hourly_rank'] = eligible.groupby(['decision_hour', 'side']).cumcount() + 1
    top = eligible[eligible.hourly_rank <= 3].copy()
    old_top = pd.read_parquet(R90 / '候选数据/固定十一币已知小时排名.parquet')
    cols = ['decision_hour', 'symbol', 'side', 'score', 'rvol', 'liquidity_rank', 'hourly_rank']
    old = old_top[cols].sort_values(cols[:3]).reset_index(drop=True)
    new = top[~top.decision_hour.isin(old_unknown)][cols].sort_values(cols[:3]).reset_index(drop=True)
    identity = ['decision_hour', 'symbol', 'side', 'liquidity_rank', 'hourly_rank']
    pd.testing.assert_frame_equal(old[identity], new[identity], check_exact=True)
    score_diff = float(np.max(np.abs(old.score.to_numpy(float) - new.score.to_numpy(float)))) if len(old) else 0.0
    rvol_diff = float(np.max(np.abs(old.rvol.to_numpy(float) - new.rvol.to_numpy(float)))) if len(old) else 0.0
    assert np.allclose(old.score, new.score, rtol=1e-10, atol=1e-11)
    assert np.allclose(old.rvol, new.rvol, rtol=1e-10, atol=1e-11)
    all_hours = set(range(int(pd.Timestamp('2022-01-01', tz='UTC').timestamp() * 1000),
                          int(pd.Timestamp('2023-01-01', tz='UTC').timestamp() * 1000), 3600000))
    known = set(map(int, complete.decision_hour.unique()))
    assert all_hours - old_unknown <= known
    recovered, remaining = old_unknown & known, old_unknown - known
    raw = pd.read_parquet(R90 / '候选数据/固定十一币潜在分钟候选.parquet')
    raw = raw[(raw.trigger_minute // 3600000 * 3600000).isin(recovered)].copy()
    bars = pd.read_parquet(R90 / '候选数据/BTC_ETH一分钟合成十五分钟.parquet')
    lookup = {(x['symbol'], int(x['open_time'])): x for x in bars.to_dict('records')}
    ranks = {(int(r.decision_hour), r.symbol, int(r.side)): {'score': float(r.score), 'rvol': float(r.rvol),
              'rank': int(r.hourly_rank), 'liquidity_rank': int(r.liquidity_rank)} for r in top.itertuples(index=False)}
    events, counts = [], Counter()
    for e in raw.to_dict('records'):
        hour = int(e['trigger_minute']) // 3600000 * 3600000
        market = classify(int(e['quarter_start']), lookup, set())
        for side, name in ((1, 'long'), (-1, 'short')):
            rank = ranks.get((hour, e['symbol'], side))
            eligible_side = bool(e[name + '_pre_rank'] and rank is not None)
            if eligible_side: e[name + '_spec'] = json.dumps({**json.loads(e[name + '_spec']), **rank}, ensure_ascii=False)
            allowed = market['market_status'] == 'market_unknown' or (market['market_status'] == 'allowed' and market['allowed_side'] == side)
            e[name + '_known_eligible'] = bool(eligible_side and allowed)
            if not e[name + '_known_eligible']: e[name + '_spec'] = 'null'
        if e['long_known_eligible'] or e['short_known_eligible']:
            e['market_prior_status'], e['market_allowed_side'] = market['market_status'], market['allowed_side']
            e['needs_next'] = bool((int(e['quarter_end']) + 60000 - 1) // 86400000 > int(e['trigger_minute']) // 86400000)
            events.append(e); counts[market['market_status']] += 1
        else: counts['filtered_before_tick'] += 1
    if events:
        candidates = pd.DataFrame(events).sort_values(['trigger_minute', 'symbol']).reset_index(drop=True)
    else:
        candidates = pd.read_parquet(R90 / '候选数据/固定十一币双币过滤潜在触价.parquet').iloc[:0].copy()
    assert candidates.observation_id.is_unique and not candidates.duplicated(['symbol', 'quarter_start']).any()
    original = pd.read_parquet(R90 / '候选数据/固定十一币双币过滤潜在触价.parquet')
    assert not set(candidates.observation_id) & set(original.observation_id)
    folder = H / '替代口径候选'; folder.mkdir(exist_ok=True)
    candidates.to_parquet(folder / '新增潜在触价.parquet', index=False)
    top[top.decision_hour.isin(recovered)].to_parquet(folder / '恢复小时排名.parquet', index=False)
    out = {'original_unknown_rank_hours': len(old_unknown), 'recovered_rank_hours': len(recovered),
           'remaining_unknown_rank_hours': len(remaining), 'remaining_unknown_hours_ms': sorted(remaining),
           'old_known_hour_ranks_unchanged': True, 'recovered_raw_potential_events': len(raw),
           'old_known_score_max_abs_float_difference': score_diff, 'old_known_rvol_max_abs_float_difference': rvol_diff,
           'extra_candidates': len(candidates), 'market_statuses_and_filtered': dict(counts),
           'candidate_sha256': sha(folder / '新增潜在触价.parquet'), 'recovered_rank_sha256': sha(folder / '恢复小时排名.parquet'),
           'hour_check_sha256': sha(H / '零成交小时来源核对.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Alternative hour semantics only; original minute feature validity remains strict, and extra paths are not yet settled.'}
    (H / '替代排名候选质量.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_CANDIDATES', json.dumps({k: v for k, v in out.items() if k != 'remaining_unknown_hours_ms'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
