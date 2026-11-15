"""Replay one previously reconciled discrepancy under the fixed one-second rule."""
import hashlib
import json
from pathlib import Path
import sys
import time

import pandas as pd

from one_second_check import first_second

H = Path(__file__).resolve().parent
P = H.parent
R54 = P / '第五十四轮_原始成交缺口敏感性'
R62 = P / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(R54))
import independent_xrp_audit as old
sys.path.insert(0, str(R62))
import one_second_observation as engine


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def fetch(kind, expected):
    for attempt in range(3):
        try:
            result = old.read_archive(kind, expected)
            print('XRP_ARCHIVE_VERIFIED', kind, flush=True)
            return result
        except Exception as exc:
            # A source mismatch and resource guard are not transient network errors.
            if 'headroom' in str(exc) or 'disk_reserve' in str(exc) or isinstance(exc, ValueError) or attempt == 2:
                raise
            print('XRP_ARCHIVE_RETRY', kind, attempt + 1, type(exc).__name__, flush=True)
            time.sleep(attempt + 1)


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结方案.md') == frozen['plan_sha256']
    assert sha(H / 'one_second_check.py') == frozen['causal_check_sha256']
    assert sha(H / '首秒边界测试.json') == frozen['causal_test_sha256']
    assert sha(R62 / 'one_second_observation.py') == frozen['one_second_engine_sha256']
    assert sha(R62 / '2024输入冻结哈希.json') == frozen['baseline_2024_manifest_sha256']
    assert sha(R62 / '2024完整批次_冻结/完整快照哈希.json') == frozen['baseline_2024_result_sha256']
    audit_path = R54 / 'XRP原始成交独立复核与敏感性.json'
    assert sha(audit_path) == frozen['previous_source_audit_sha256']
    prior = json.loads(audit_path.read_text(encoding='utf-8'))
    expected = {a['kind']: a for a in prior['archives']}
    assert {k: v['sha256'] for k, v in expected.items()} == frozen['prior_official_archive_sha256']
    manifest = json.loads((R62 / '2024输入冻结哈希.json').read_text(encoding='utf-8'))
    folder = R62 / '2024冻结输入'
    for name in ('candidates.parquet', 'baseline_signal.parquet'):
        assert sha(folder / name) == manifest['input_sha256'][name]
    candidates = pd.read_parquet(folder / 'candidates.parquet')
    signals = pd.read_parquet(folder / 'baseline_signal.parquet')
    e = candidates.loc[candidates.observation_id.eq(old.OBS)].iloc[0].to_dict()
    s = signals.loc[signals.observation_id.eq(old.OBS)].iloc[0]
    assert s['status'] == 'prior_source_disagreement' and int(e['trigger_minute']) == int(e['quarter_start']) == old.START
    assert e['market_prior_status'] == 'allowed' and int(e['market_allowed_side']) == 1 and bool(e['long_known_eligible'])
    sources = []
    body, meta = fetch('klines', expected['klines']); sources.append(meta); bar = old.read_minute_bar(body); del body
    body, meta = fetch('aggTrades', expected['aggTrades']); sources.append(meta); agg = old.read_window(body, 'aggTrades'); del body
    body, meta = fetch('trades', expected['trades']); sources.append(meta); raw = old.read_window(body, 'trades'); del body
    agg_min = [r for r in agg if r[0] < old.START + 60000]
    raw_min = [r for r in raw if r[0] < old.START + 60000]
    official = [bar[k] for k in ('open', 'high', 'low', 'close')]
    av, rv = old.ohlc(agg_min), old.ohlc(raw_min)
    assert rv == official and av[0] != official[0] and av[1:] == official[1:]
    assert len(raw_min) == bar['count']
    assert old.close(sum((r[3] for r in raw_min), old.Decimal(0)), bar['volume'], 1e-6)
    assert old.close(sum((r[2] * r[3] for r in raw_min), old.Decimal(0)), bar['quote_volume'], 1e-5)
    assert [str(x) for x in official] == prior['kline_ohlc']
    result = first_second(agg, raw, old.START, old.Decimal(str(e['upper'])), old.Decimal(str(e['lower'])),
                          bool(e['long_known_eligible']), bool(e['short_known_eligible']))
    assert result['status'] in ('known_no_order_flow', 'known_no_order_direction', 'qualified_requires_path',
                                'unknown_first_cross', 'unknown_reference', 'unknown_flow')
    # Compare with frozen engine only after the raw source independently reconciles.
    if result['status'] in ('known_no_order_flow', 'qualified_requires_path'):
        tape = pd.DataFrame([{'transact_time': r[0], 'agg_trade_id': r[1], 'price': float(r[2]),
                              'quantity': float(r[3]), 'is_buyer_maker': r[4]} for r in agg])
        patched = pd.DataFrame([{'open': float(av[0]), 'high': float(av[1]), 'low': float(av[2]), 'close': float(av[3])}], index=[old.START])
        check = engine.decide(e, tape, patched)
        assert check['decision_ts'] == result['cross_ts'] and check['side'] == result['side']
        assert check['entry_exec_ts'] == result['reference_ts'] and old.close(check['raw_entry_1s'], result['reference_price'])
        assert check['one_count'] == result['aggregate_count'] and old.close(check['buy_notional'], result['buy']) and old.close(check['sell_notional'], result['sell'])
        if result['status'] == 'known_no_order_flow':
            assert check['status'] == 'flow_filter_not_met'
        else:
            assert check['status'] in ('qualified', 'known_risk_rejected')
    result_path = H / '单例一秒复核结果.json'
    out = {'observation_id': old.OBS, 'result': result, 'archives': sources, 'frozen_sha256': sha(H / '冻结时点.json'),
           'candidate_sha256': sha(folder / 'candidates.parquet'), 'code_sha256': sha(Path(__file__)),
           'minute_check': {'raw_count': len(raw_min), 'official_count': bar['count'], 'raw_ohlc': [str(x) for x in rv],
                            'aggregate_ohlc': [str(x) for x in av], 'official_ohlc': [str(x) for x in official]},
           'note': 'Post-hoc single-event source sensitivity only; other original unknowns and frozen results remain unchanged.'}
    result_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('XRP_ONESEC_RECHECK', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
