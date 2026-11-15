"""Independently rebuild recovered hourly ranks and every added candidate gate."""
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
R90 = H.parent / '第九十轮_二零二二公开行情'
sys.path.insert(0, str(R90)); import replay_2022 as runner
HOUR, Q = 3600000, 900000


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def market(q, lookup):
    values = []
    for sym in ('BTCUSDT', 'ETHUSDT'):
        bars = [lookup.get((sym, t)) for t in range(q - 21 * Q, q, Q)]
        if any(b is None or min(b['volume'], b['count'], b['open'], b['close']) <= 0 for b in bars):
            values.append(('unknown', 0)); continue
        past = sum(int(b['count']) for b in bars[:20]); n = int(bars[-1]['count'])
        side = 1 if bars[-1]['close'] > bars[-1]['open'] else -1 if bars[-1]['close'] < bars[-1]['open'] else 0
        if past <= 0: values.append(('unknown', 0))
        elif 40 * n < 3 * past or side == 0: values.append(('rejected', 0))
        else: values.append(('passed', side))
    if any(x[0] == 'rejected' for x in values): return 'known_no_order', 0
    if any(x[0] == 'unknown' for x in values): return 'market_unknown', 0
    if values[0][1] != values[1][1]: return 'known_no_order', 0
    return 'allowed', values[0][1]


def main():
    runner.guard(start=True)
    path = H / '替代排名候选质量.json'; quality = json.loads(path.read_text(encoding='utf-8'))
    assert quality['code_sha256'] == sha(H / 'prepare_extra_candidates.py')
    assert quality['hour_check_sha256'] == sha(H / '零成交小时来源核对.json')
    assert quality['candidate_sha256'] == sha(H / '替代口径候选/新增潜在触价.parquet')
    assert quality['recovered_rank_sha256'] == sha(H / '替代口径候选/恢复小时排名.parquet')
    hour_data = json.loads((H / '零成交小时来源核对.json').read_text(encoding='utf-8'))
    source_hours = {}
    for x in hour_data['hourly_sources']:
        assert sha(Path(x['path'])) == x['sha256']
        d = pd.read_parquet(x['path']); d['key'] = d.open_time // HOUR
        source_hours[x['symbol']] = d.set_index('key')
    daily = pd.read_parquet(R90 / '候选数据/固定十一币历史日排名.parquet')
    ranks = {(r.day, r.symbol): int(r.liquidity_rank) for r in daily.itertuples(index=False)}
    q90 = json.loads((R90 / '二零二二候选准备质量.json').read_text(encoding='utf-8'))
    recovered = set(q90['unknown_rank_hours_ms']) - set(quality['remaining_unknown_hours_ms'])
    raw = pd.read_parquet(R90 / '候选数据/固定十一币潜在分钟候选.parquet')
    raw = raw[(raw.trigger_minute // HOUR * HOUR).isin(recovered)]
    times = sorted(set(int(x) // HOUR * HOUR for x in raw.trigger_minute))
    top = pd.read_parquet(H / '替代口径候选/恢复小时排名.parquet')
    independent = {}
    for ts in times:
        cur = ts // HOUR - 1; day = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m-%d')
        proposed = []
        for sym, hs in source_hours.items():
            prices = hs.reindex(range(cur - 24, cur + 1)).close.to_numpy(float)
            quote = float(hs.reindex([cur]).quote_volume.iloc[0])
            lagged = hs.reindex([cur - 24 * i for i in range(1, 21)]).quote_volume.to_numpy(float)
            assert np.isfinite(prices).all() and np.isfinite(quote) and np.isfinite(lagged).all() and (prices > 0).all() and (lagged > 0).all()
            returns = np.diff(np.log(prices)); sigma = float(np.std(returns, ddof=1)); assert sigma > 0
            score, rvol = float(returns[-6:].sum() / sigma), float(quote / np.median(lagged))
            if rvol >= 1.5 and score != 0:
                proposed.append({'symbol': sym, 'side': 1 if score > 0 else -1, 'score': score, 'rvol': rvol, 'liquidity_rank': ranks[(day, sym)]})
        expected = []
        for side in (-1, 1):
            g = sorted((x for x in proposed if x['side'] == side), key=lambda x: (-abs(x['score']), x['liquidity_rank'], x['symbol']))
            for i, x in enumerate(g[:3], 1): expected.append({**x, 'rank': i})
        got = top[top.decision_hour.eq(ts)]
        assert len(got) == len(expected)
        for x in expected:
            r = got[(got.symbol == x['symbol']) & (got.side == x['side'])]
            assert len(r) == 1; z = r.iloc[0]
            assert int(z.hourly_rank) == x['rank'] and int(z.liquidity_rank) == x['liquidity_rank']
            assert math.isclose(float(z.score), x['score'], rel_tol=1e-9, abs_tol=1e-10)
            assert math.isclose(float(z.rvol), x['rvol'], rel_tol=1e-9, abs_tol=1e-10)
            independent[(ts, x['symbol'], x['side'])] = x
    bars = pd.read_parquet(R90 / '候选数据/BTC_ETH一分钟合成十五分钟.parquet')
    lookup = {(r['symbol'], int(r['open_time'])): r for r in bars.to_dict('records')}
    expected_candidates = {}
    for e in raw.to_dict('records'):
        t = int(e['trigger_minute']) // HOUR * HOUR
        state, allowed_side = market(int(e['quarter_start']), lookup)
        eligible = {}
        for side, name in ((1, 'long'), (-1, 'short')):
            rank = independent.get((t, e['symbol'], side))
            ok = bool(e[name + '_pre_rank'] and rank and (state == 'market_unknown' or (state == 'allowed' and allowed_side == side)))
            eligible[name] = ok
        if any(eligible.values()): expected_candidates[e['observation_id']] = (e, state, allowed_side, eligible)
    candidates = pd.read_parquet(H / '替代口径候选/新增潜在触价.parquet')
    assert set(candidates.observation_id) == set(expected_candidates)
    for c in candidates.to_dict('records'):
        e, state, allowed, eligible = expected_candidates[c['observation_id']]
        assert c['market_prior_status'] == state and int(c['market_allowed_side']) == allowed
        for side, name in ((1, 'long'), (-1, 'short')):
            assert bool(c[name + '_known_eligible']) == eligible[name]
            if eligible[name]:
                z = json.loads(c[name + '_spec']); rank = independent[(int(c['trigger_minute']) // HOUR * HOUR, c['symbol'], side)]
                original = json.loads(e[name + '_spec'])
                assert all(z[k] == v for k, v in original.items())
                assert z['rank'] == rank['rank'] and z['liquidity_rank'] == rank['liquidity_rank']
                assert math.isclose(z['score'], rank['score'], rel_tol=1e-9, abs_tol=1e-10)
                assert math.isclose(z['rvol'], rank['rvol'], rel_tol=1e-9, abs_tol=1e-10)
    result = {'all_checks_pass': True, 'raw_potential_events_checked': len(raw), 'hourly_rank_times_rebuilt': len(times),
              'candidate_gates_checked': len(candidates), 'candidate_quality_sha256': sha(path),
              'hour_audit_sha256': sha(H / '零成交小时独立核验.json'), 'code_sha256': sha(Path(__file__)),
              'note': 'Alternative semantics only; first-second paths and risk not checked here.'}
    (H / '替代排名候选独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT94_CANDIDATE_AUDIT', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
