"""Reconcile all three previously unknown Aug-Oct candidates against raw trades."""
from decimal import Decimal
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

H = Path(__file__).resolve().parent
R81 = H.parent / '第八十一轮_八至十月一秒观察'
R80 = H.parent / '第八十轮_未知候选一秒复核'
sys.path.insert(0, str(R81))
import run_replay as runner
sys.path.insert(0, str(R80))
from one_second_check import first_second

D = Decimal
BASE = 'https://data.binance.vision/data/futures/um/daily/'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def fetch(kind, sym, day, expected=None):
    name = f'{sym}-1m-{day}.zip' if kind == 'klines' else f'{sym}-{kind}-{day}.zip'
    sub = f'klines/{sym}/1m/{name}' if kind == 'klines' else f'{kind}/{sym}/{name}'
    url = BASE + sub
    for attempt in range(3):
        try:
            runner.guard()
            with requests.Session() as s:
                c = s.get(url + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
                parts = c.text.split()
                assert len(parts) >= 2 and re.fullmatch('[0-9a-fA-F]{64}', parts[0]) and Path(parts[1]).name == name
                with s.get(url, stream=True, timeout=(15, 120)) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_content(262144):
                        runner.guard()
                        body.extend(chunk)
                        if len(body) > 50_000_000:
                            raise ValueError('archive_exceeds_frozen_resource_cap')
            body = bytes(body)
            digest = hashlib.sha256(body).hexdigest()
            assert digest == parts[0].lower()
            if expected:
                assert digest == expected['sha256'] and len(body) == expected['bytes']
            return body, {'kind': kind, 'symbol': sym, 'day': day, 'url': url, 'sha256': digest, 'bytes': len(body)}
        except requests.exceptions.RequestException as exc:
            if attempt == 2:
                raise
            print('EXT83_RETRY', sym, day, kind, type(exc).__name__, flush=True)
            time.sleep(attempt + 1)


def window(body, kind, start, end):
    values = []
    timecol = 'transact_time' if kind == 'aggTrades' else 'time'
    for chunk in pd.read_csv(io.BytesIO(body), compression='zip', chunksize=100000, dtype=str):
        runner.guard()
        assert timecol in chunk and 'price' in chunk and 'is_buyer_maker' in chunk
        idcol = 'agg_trade_id' if kind == 'aggTrades' else ('id' if 'id' in chunk else 'trade_id')
        qtycol = 'quantity' if 'quantity' in chunk else 'qty'
        t = chunk[timecol].to_numpy(dtype=np.int64)
        sub = chunk.loc[(t >= start) & (t < end), [timecol, idcol, 'price', qtycol, 'is_buyer_maker']]
        for ts, ident, px, qty, maker in sub.itertuples(index=False, name=None):
            maker = maker.lower()
            assert maker in ('true', 'false')
            values.append((int(ts), int(ident), D(px), D(qty), maker))
            if len(values) > 500000:
                raise ValueError('event_window_exceeds_memory_cap')
    values.sort(key=lambda x: (x[0], x[1]))
    return values


def ohlc(rows):
    return [rows[0][2], max(x[2] for x in rows), min(x[2] for x in rows), rows[-1][2]]


def same(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def task(e, frozen):
    obs, sym, day, start = e['observation_id'], e['contract'], e['day'], int(e['trigger_minute'])
    assert start == int(e['quarter_start'])  # All three are opening candidates.
    expected = {x['kind']: x for x in frozen['archives'] if x['day'] == day}
    assert 'klines' in expected and 'aggTrades' in expected
    archives = []
    body, meta = fetch('klines', sym, day, expected['klines']); archives.append(meta)
    allbars = pd.read_csv(io.BytesIO(body), compression='zip', dtype=str); del body
    matches = allbars[allbars.open_time.astype('int64').eq(start)]
    assert len(matches) == 1
    bar = matches.iloc[0]
    body, meta = fetch('aggTrades', sym, day, expected['aggTrades']); archives.append(meta)
    agg = window(body, 'aggTrades', start, int(e['quarter_end']) + 60000); del body
    body, meta = fetch('trades', sym, day); archives.append(meta)
    raw = window(body, 'trades', start, int(e['quarter_end']) + 60000); del body
    am, rm = [x for x in agg if x[0] < start + 60000], [x for x in raw if x[0] < start + 60000]
    if not am or not rm:
        return {'observation_id': obs, 'status': 'unknown_missing_minute_trades', 'archives': archives}
    official = [D(bar[k]) for k in ('open', 'high', 'low', 'close')]
    av, rv = ohlc(am), ohlc(rm)
    count = int(bar.get('count', bar.get('number_of_trades')))
    volume = sum((x[3] for x in rm), D(0))
    quote = sum((x[2] * x[3] for x in rm), D(0))
    match = (rv == official and av[0] != official[0] and av[1:] == official[1:] and len(rm) == count and
             abs(volume - D(bar['volume'])) < D('.000001') and abs(quote - D(bar['quote_volume'])) < D('.00001'))
    evidence = {'official_ohlc': [str(x) for x in official], 'raw_ohlc': [str(x) for x in rv],
                'aggregate_ohlc': [str(x) for x in av], 'raw_minute_count': len(rm), 'kline_trade_count': count,
                'raw_volume': str(volume), 'official_volume': bar['volume'],
                'raw_quote_volume': str(quote), 'official_quote_volume': bar['quote_volume']}
    if not match:
        return {'observation_id': obs, 'status': 'unknown_ohlc_count_or_volume', 'evidence': evidence, 'archives': archives}
    result = first_second(agg, raw, start, D(str(e['upper'])), D(str(e['lower'])),
                          bool(e['long_known_eligible']), bool(e['short_known_eligible']))
    if result['status'] not in ('known_no_order_flow', 'known_no_order_direction', 'qualified_requires_path'):
        return {'observation_id': obs, 'status': result['status'], 'one_second': result, 'evidence': evidence, 'archives': archives}
    if result['status'] == 'known_no_order_direction':
        return {'observation_id': obs, 'status': result['status'], 'one_second': result, 'evidence': evidence, 'archives': archives}
    def make_tape(rows):
        return pd.DataFrame([{'transact_time': x[0], 'agg_trade_id': x[1], 'price': float(x[2]),
                              'quantity': float(x[3]), 'is_buyer_maker': x[4]} for x in rows])
    patched = pd.DataFrame([{'open': float(av[0]), 'high': float(av[1]), 'low': float(av[2]), 'close': float(av[3])}], index=[start])
    a = runner.engine.decide(e, make_tape(agg), patched)
    assert a['decision_ts'] == result['cross_ts'] and a['side'] == result['side']
    assert a['entry_exec_ts'] == result['reference_ts'] and same(a['raw_entry_1s'], result['reference_price'])
    assert a['one_count'] == result['aggregate_count'] and same(a['buy_notional'], result['buy']) and same(a['sell_notional'], result['sell'])
    if result['status'] == 'known_no_order_flow':
        assert a['status'] == 'flow_filter_not_met'
        return {'observation_id': obs, 'status': 'known_no_order_flow', 'one_second': result, 'evidence': evidence, 'archives': archives}
    if a['status'] == 'known_risk_rejected':
        return {'observation_id': obs, 'status': 'known_no_order_precheck', 'one_second': result, 'prechecks': a['prechecks'],
                'evidence': evidence, 'archives': archives}
    assert a['status'] == 'qualified'
    rawbars = pd.DataFrame([{'open': float(official[0]), 'high': float(official[1]), 'low': float(official[2]), 'close': float(official[3])}], index=[start])
    b = runner.engine.decide(e, make_tape(raw), rawbars)
    fields = ['status', 'entry_ts', 'entry_raw', 'entry_fill', 'exit_signal_ts', 'exit_ts', 'exit_raw', 'exit_fill', 'reason']
    agrees = b['status'] == 'qualified' and set(a['paths']) == set(b['paths'])
    if agrees:
        for variant in a['paths']:
            aa, bb = a['paths'][variant], b['paths'][variant]
            agrees = agrees and all(k in aa and k in bb and (same(aa[k], bb[k]) if isinstance(aa[k], float) else aa[k] == bb[k]) for k in fields)
    return {'observation_id': obs, 'status': 'qualified_risk_not_yet_verified' if agrees else 'unknown_path_disagreement',
            'one_second': result, 'aggregate_paths': a['paths'], 'evidence': evidence, 'archives': archives}


def main():
    runner.guard(start=True)
    f = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert f['plan_sha256'] == sha(H / '冻结研究方案.md') and f['r81_runner_sha256'] == sha(R81 / 'run_replay.py')
    assert f['reference_check_sha256'] == sha(R80 / 'one_second_check.py')
    assert f['one_second_engine_sha256'] == sha(runner.R62 / 'one_second_observation.py')
    assert f['r81_frozen_sha256'] == sha(R81 / '冻结结果/冻结哈希.json')
    candidates = pd.read_parquet(runner.OLD / '候选数据/固定十一币双币过滤潜在触价.parquet').set_index('observation_id')
    assert f['candidate_sha256'] == sha(runner.OLD / '候选数据/固定十一币双币过滤潜在触价.parquet')
    output = []
    for i, item in enumerate(f['candidates'], 1):
        assert item['checkpoint_sha256'] == sha(Path(item['checkpoint']))
        e = candidates.loc[item['observation_id']].to_dict(); e['observation_id'] = item['observation_id']
        try:
            r = task(e, item)
        except Exception as exc:
            r = {'observation_id': e['observation_id'], 'status': 'unknown_exception', 'error': type(exc).__name__ + ':' + str(exc)[:180]}
        output.append(r)
        print('EXT83_RECONCILE', i, '/3', r['observation_id'], r['status'], flush=True)
        if r['status'] == 'unknown_exception' and 'headroom' in r['error']:
            break
    if len(output) < 3:
        seen = {x['observation_id'] for x in output}
        output.extend({'observation_id': x['observation_id'], 'status': 'unknown_not_processed'} for x in f['candidates'] if x['observation_id'] not in seen)
    result = {'candidates': output, 'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
              'note': 'Post-hoc source sensitivity; qualified entries remain unknown pending full risk audit.'}
    (H / '三个候选来源复核.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT83_STOP', [(x['observation_id'], x['status']) for x in output], flush=True)


if __name__ == '__main__':
    main()
