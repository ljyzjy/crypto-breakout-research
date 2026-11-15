"""Extend the audited fixed-11 candidate engine to frozen 2022 minutes."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
REF = P / '第四十六轮_固定十一加密币跨时段'
sys.path.insert(0, str(REF))
sys.path.insert(0, str(P / '第四十轮_BTC_ETH事前活跃度'))
import prepare_fixed11_chunked as prep
import minute_features_chunked as original
import chunk_exact
from market_decisions import classify
import acquire_klines as data_guard

M, Q = 60000, 900000
START, BEGIN, END = '2021-12-01', '2022-01-01', '2023-01-01'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def ms(value):
    return int(pd.Timestamp(value, tz='UTC').timestamp() * 1000)


def patched_features():
    path = REF / 'minute_features_chunked.py'
    source = path.read_text(encoding='utf-8')
    old = "elif year==2026:lo=int(pd.Timestamp('2026-05-01',tz='UTC').timestamp()*1000);hi=int(pd.Timestamp('2026-08-01',tz='UTC').timestamp()*1000)"
    new = old + "\n    elif year==2022:lo=int(EXT_BEGIN_MS);hi=int(EXT_END_MS)"
    assert source.count(old) == 1
    code = source.replace(old, new)
    module = types.ModuleType('ext90_features')
    module.__file__ = str(path); module.EXT_BEGIN_MS, module.EXT_END_MS = ms(BEGIN), ms(END)
    sys.modules[module.__name__] = module
    exec(compile(code, str(path), 'exec'), module.__dict__)
    return module, hashlib.sha256(code.encode()).hexdigest()


def parity_and_future(module, path):
    frame = pd.read_parquet(path)
    lo, hi = ms('2022-06-01'), ms('2022-06-08')
    frame = frame[frame.ts.between(lo, hi - 1)].sort_values('ts')
    grid = np.arange(lo, hi, M, dtype=np.int64)
    assert len(frame) == len(grid) and np.array_equal(frame.ts.to_numpy(np.int64), grid)
    a = frame[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count']].to_numpy(float)
    days = set(pd.to_datetime(grid[::1440], unit='ms', utc=True).strftime('%Y-%m-%d'))
    h1, e1, _ = module.derive(a, grid, 'BTCUSDT', 2022, days)
    chunk_exact.m = module
    h2, e2, _ = chunk_exact.derive_chunked(a, grid, 'BTCUSDT', 2022, days)
    pd.testing.assert_frame_equal(h1, h2, check_exact=True)
    assert e1 == e2
    modified = a.copy(); cutoff = len(grid) - 1440
    modified[cutoff:, :4] *= 1.01; modified[cutoff:, 4:] *= 1.05
    _, changed, _ = module.derive(modified, grid, 'BTCUSDT', 2022, days)
    assert [x for x in e1 if x['trigger_minute'] < int(grid[cutoff])] == [x for x in changed if x['trigger_minute'] < int(grid[cutoff])]
    return {'all_checks_pass': True, 'minute_rows': len(grid), 'events': len(e1),
            'checks': ['2022_chunk_vs_full_exact', 'future_minute_perturbation']}


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, path in frozen['source_paths'].items(): assert sha(Path(path)) == frozen['source_sha256'][name]
    quality_path = H / '二零二二分钟数据质量.json'
    quality = json.loads(quality_path.read_text(encoding='utf-8'))
    assert quality['all_symbols_verified'] and quality['frozen_sha256'] == sha(H / '冻结时点.json')
    supplement_path = H / '二零二二日档补源质量.json'
    supplement = json.loads(supplement_path.read_text(encoding='utf-8'))
    assert supplement['original_quality_sha256'] == sha(quality_path)
    assert supplement['amendment_sha256'] == sha(H / '日档补源规则冻结.json')
    assert supplement['code_sha256'] == sha(H / 'fill_missing_days.py')
    daily_audit = json.loads((H / '日档补源独立核验.json').read_text(encoding='utf-8'))
    assert daily_audit['all_checks_pass'] and daily_audit['source_sha256'] == sha(supplement_path)
    assert daily_audit['code_sha256'] == sha(H / 'audit_daily_repair.py')
    root = Path(frozen['data_root']); data_guard.guard(root, start=True)
    sources = {x['symbol']: x for x in supplement['selected_sources']}
    assert set(sources) == set(prep.SYMBOLS)
    for x in sources.values(): assert sha(Path(x['path'])) == x['sha256']
    module, patch_sha = patched_features()
    parity = parity_and_future(module, Path(sources['BTCUSDT']['path']))
    prep.WINDOWS = {2022: (START, BEGIN, END)}
    chunk_exact.m = module; prep.derive = chunk_exact.derive_chunked
    prep.WORK = root / 'candidate_chunks'; prep.WORK.mkdir(parents=True, exist_ok=True)
    fp = hashlib.sha256((sha(H / '冻结时点.json') + sha(quality_path) + sha(supplement_path) + sha(Path(__file__)) + patch_sha).encode()).hexdigest()
    chunks = []
    for sym in prep.SYMBOLS:
        data_guard.guard(root)
        chunks.append(prep.process(2022, sym, Path(sources[sym]['path']), fp))
        print('EXT90_CANDIDATE_SYMBOL', len(chunks), '/11', sym, flush=True)
    out = H / '候选数据'; out.mkdir(exist_ok=True)
    days = pd.concat([pd.read_parquet(x['days_path']) for x in chunks], ignore_index=True)
    days = days[days.day.ge(BEGIN) & days.day.lt(END) & np.isfinite(days.past_30d_quote)].copy()
    days['eligible_count'] = days.groupby('day').symbol.transform('size')
    days = days[days.eligible_count.eq(11)].sort_values(['day', 'past_30d_quote', 'symbol'], ascending=[True, False, True])
    days['liquidity_rank'] = days.groupby('day').cumcount() + 1
    days.to_parquet(out / '固定十一币历史日排名.parquet', index=False)
    indicator = prep.hourly_indicator()
    features = []
    for item in chunks:
        g = indicator(pd.read_parquet(item['hours_path']), START, END); g['symbol'] = item['symbol']; features.append(g)
    feature = pd.concat(features, ignore_index=True)
    feature['day'] = pd.to_datetime(feature.decision_hour, unit='ms', utc=True).dt.strftime('%Y-%m-%d')
    merged = days[['day', 'symbol', 'liquidity_rank']].merge(feature, on=['day', 'symbol'], how='left', validate='one_to_many')
    assert len(merged) == 24 * len(days)
    merged['valid_feature'] = np.isfinite(merged.score) & np.isfinite(merged.rvol)
    merged['valid_count'] = merged.groupby('decision_hour').valid_feature.transform('sum')
    complete = merged[merged.valid_count.eq(11)]
    eligible = complete[complete.valid_feature & complete.rvol.ge(1.5) & complete.score.ne(0)].copy()
    eligible['side'] = np.where(eligible.score > 0, 1, -1); eligible['strength'] = eligible.score.abs()
    eligible = eligible.sort_values(['decision_hour', 'side', 'strength', 'liquidity_rank', 'symbol'], ascending=[True, True, False, True, True])
    eligible['hourly_rank'] = eligible.groupby(['decision_hour', 'side']).cumcount() + 1
    top = eligible[eligible.hourly_rank <= 3]; top.to_parquet(out / '固定十一币已知小时排名.parquet', index=False)
    raw_pieces = [pd.read_parquet(x['events_path']) for x in chunks]
    raw = pd.concat([x for x in raw_pieces if len(x)], ignore_index=True)
    assert raw.observation_id.is_unique
    raw.to_parquet(out / '固定十一币潜在分钟候选.parquet', index=False)
    bars = pd.concat([pd.read_parquet(x['market_path']) for x in chunks if x['market_path']], ignore_index=True)
    assert not bars.duplicated(['symbol', 'open_time']).any()
    bars.to_parquet(out / 'BTC_ETH一分钟合成十五分钟.parquet', index=False)
    lookup = {(x['symbol'], int(x['open_time'])): x for x in bars.to_dict('records')}
    ranks = {(int(r.decision_hour), r.symbol, int(r.side)): {'score': float(r.score), 'rvol': float(r.rvol),
              'rank': int(r.hourly_rank), 'liquidity_rank': int(r.liquidity_rank)} for r in top.itertuples(index=False)}
    quarters = sorted(set(map(int, raw.quarter_start)))
    markets = {q: classify(q, lookup, set()) for q in quarters}
    events, counts = [], Counter()
    for e in raw.to_dict('records'):
        hour = int(e['trigger_minute']) // 3600000 * 3600000
        market = markets[int(e['quarter_start'])]
        for side, name in ((1, 'long'), (-1, 'short')):
            rank = ranks.get((hour, e['symbol'], side))
            eligible_side = bool(e[name + '_pre_rank'] and rank is not None)
            if eligible_side:
                e[name + '_spec'] = json.dumps({**json.loads(e[name + '_spec']), **rank}, ensure_ascii=False)
            allowed = market['market_status'] == 'market_unknown' or (market['market_status'] == 'allowed' and market['allowed_side'] == side)
            e[name + '_known_eligible'] = bool(eligible_side and allowed)
            if not e[name + '_known_eligible']: e[name + '_spec'] = 'null'
        if e['long_known_eligible'] or e['short_known_eligible']:
            e['market_prior_status'], e['market_allowed_side'] = market['market_status'], market['allowed_side']
            e['needs_next'] = bool((int(e['quarter_end']) + M - 1) // 86400000 > int(e['trigger_minute']) // 86400000)
            events.append(e); counts[market['market_status']] += 1
        else:
            counts['filtered_before_tick'] += 1
    candidates = pd.DataFrame(events).sort_values(['trigger_minute', 'symbol']).reset_index(drop=True)
    assert candidates.observation_id.is_unique and not candidates.duplicated(['symbol', 'quarter_start']).any()
    candidates.to_parquet(out / '固定十一币双币过滤潜在触价.parquet', index=False)
    valid_hours = set(int(x) for x in complete.decision_hour.unique())
    expected_hours = set(range(ms(BEGIN), ms(END), 3600000))
    unknown_hours = sorted(expected_hours - valid_hours)
    missing_days = {}
    for sym, info in sources.items():
        frame = pd.read_parquet(info['path'], columns=['ts'])
        t = frame.ts.to_numpy(dtype=np.int64)
        grid = np.arange(ms(BEGIN), ms(END), M, dtype=np.int64)
        absent = np.setdiff1d(grid, t, assume_unique=True)
        if len(absent):
            missing_days[sym] = sorted(set(pd.to_datetime(absent, unit='ms', utc=True).strftime('%Y-%m-%d')))
    files = sorted(out.glob('*.parquet'))
    result = {'period_utc': [BEGIN, END], 'warm_start_utc': START, 'symbols': prep.SYMBOLS,
              'calendar_days': 365, 'complete_liquidity_days': int(days.day.nunique()),
              'rankable_hours': len(valid_hours), 'unknown_rank_hours_count': len(unknown_hours), 'unknown_rank_hours_ms': unknown_hours,
              'missing_current_minute_days': missing_days, 'raw_potential_events': len(raw),
              'post_hour_and_market_candidates': len(candidates), 'candidate_market_statuses': candidates.market_prior_status.value_counts().to_dict(),
              'market_quarter_statuses': dict(Counter(x['market_status'] for x in markets.values())),
              'parity_and_causality': parity, 'patched_feature_sha256': patch_sha, 'data_quality_sha256': sha(quality_path),
              'daily_supplement_sha256': sha(supplement_path), 'remaining_missing_minutes': supplement['remaining_missing_minutes'],
              'daily_audit_sha256': sha(H / '日档补源独立核验.json'),
              'outputs_sha256': {p.name: sha(p) for p in files}, 'code_sha256': sha(Path(__file__)),
              'note': 'Candidate generation only; unrankable hours, missing minutes, unknown market conditions and later source failures must stay unknown.'}
    (H / '二零二二候选准备质量.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_CANDIDATES', json.dumps({k: v for k, v in result.items() if k not in ('unknown_rank_hours_ms', 'outputs_sha256')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
