"""Independent raw/aggregate replay and scalar precheck of the BNB no-order."""
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import zipfile

import pyarrow.parquet as pq
import requests

H = Path(__file__).resolve().parent
R81 = H.parent / '第八十一轮_八至十月一秒观察'
sys.path.insert(0, str(R81))
import run_replay as runner

D = Decimal
OBS = 'opening|BNBUSDT|1787213700000'
START = 1787213700000


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def get(meta):
    for attempt in range(3):
        try:
            runner.guard()
            with requests.Session() as s:
                c = s.get(meta['url'] + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
                parts = c.text.split()
                assert parts[0].lower() == meta['sha256'] and Path(parts[1]).name == Path(meta['url']).name
                r = s.get(meta['url'], timeout=(15, 120)); r.raise_for_status()
                body = r.content
            assert len(body) == meta['bytes'] and hashlib.sha256(body).hexdigest() == meta['sha256']
            return body
        except requests.exceptions.RequestException as exc:
            if attempt == 2:
                raise
            print('EXT83_BNB_RETRY', meta['kind'], type(exc).__name__, flush=True)
            time.sleep(attempt + 1)


def csvrows(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].endswith('.csv')
        with io.TextIOWrapper(z.open(names[0]), encoding='utf-8-sig', newline='') as f:
            yield from csv.DictReader(f)


def scan(body, kind):
    rows = []
    for i, x in enumerate(csvrows(body), 1):
        if i % 100000 == 0:
            runner.guard()
        ts = int(x['transact_time'] if kind == 'aggTrades' else x['time'])
        if START <= ts < START + 120000:
            ident = int(x['agg_trade_id'] if kind == 'aggTrades' else x.get('id', x.get('trade_id')))
            quantity = x.get('quantity', x.get('qty'))
            maker = x['is_buyer_maker'].lower()
            assert maker in ('true', 'false')
            rows.append((ts, ident, D(x['price']), D(quantity), maker))
    return sorted(rows, key=lambda x: (x[0], x[1]))


def manual_pre(side, ref, ref_ts, cross, stop, atr, end, lev):
    if ((ref_ts // 60000 + 480) % 1440) >= 1320:
        return 'late_day_known'
    if ref_ts + 5000 >= end:
        return 'insufficient_candle_time_known'
    estimate = ref * (1 + side * .0005)
    distance, signal_distance = side * (estimate - stop), side * (cross - stop)
    if side * (estimate - cross) > .25 * atr:
        return 'reference_deviation_known'
    if distance <= 0 or distance > 1.5 * atr or 2 * distance / estimate < .006 or 2 * signal_distance / cross < .006:
        return 'reference_risk_or_cost_known'
    if distance / estimate + .003 >= .5 * (1 / lev - .01):
        return 'reference_liquidation_buffer_known'
    return 'passed'


def main():
    runner.guard(start=True)
    path = H / '三个候选来源复核.json'
    output = json.loads(path.read_text(encoding='utf-8'))
    assert output['frozen_sha256'] == sha(H / '冻结时点.json') and output['code_sha256'] == sha(H / 'reconcile_three.py')
    x = next(x for x in output['candidates'] if x['observation_id'] == OBS)
    assert x['status'] == 'known_no_order_precheck'
    archives = {a['kind']: a for a in x['archives']}
    bars = [r for r in csvrows(get(archives['klines'])) if int(r['open_time']) == START]
    assert len(bars) == 1
    bar = bars[0]
    agg = scan(get(archives['aggTrades']), 'aggTrades')
    raw = scan(get(archives['trades']), 'trades')
    am = [r for r in agg if r[0] < START + 60000]
    rm = [r for r in raw if r[0] < START + 60000]
    def ohlc(v):
        return [v[0][2], max(z[2] for z in v), min(z[2] for z in v), v[-1][2]]
    official = [D(bar[k]) for k in ('open', 'high', 'low', 'close')]
    assert ohlc(rm) == official and ohlc(am)[1:] == official[1:] and ohlc(am)[0] != official[0]
    assert len(rm) == int(bar.get('count', bar.get('number_of_trades')))
    assert abs(sum(v[3] for v in rm) - D(bar['volume'])) < D('.000001')
    assert abs(sum(v[2] * v[3] for v in rm) - D(bar['quote_volume'])) < D('.00001')
    candidate_path = runner.OLD / '候选数据/固定十一币双币过滤潜在触价.parquet'
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(candidate_path) == frozen['candidate_sha256']
    candidates = [r for r in pq.read_table(candidate_path).to_pylist() if r['observation_id'] == OBS]
    assert len(candidates) == 1
    e = candidates[0]
    upper, lower = D(str(e['upper'])), D(str(e['lower']))
    ac = next(v for v in am if v[2] > upper or v[2] < lower)
    rc = next(v for v in rm if v[2] > upper or v[2] < lower)
    assert (ac[0], ac[2]) == (rc[0], rc[2])
    side = 1 if ac[2] > upper else -1
    assert side == 1 and e['long_known_eligible']
    ar = next(v for v in agg if v[0] >= ac[0] + 1000)
    rr = next(v for v in raw if v[0] >= ac[0] + 1000)
    assert (ar[0], ar[2]) == (rr[0], rr[2])
    aw = [v for v in agg if ac[0] < v[0] < ac[0] + 1000]
    rw = [v for v in raw if ac[0] < v[0] < ac[0] + 1000]
    def flow(v):
        return (sum((z[2] * z[3] for z in v if z[4] == 'false'), D(0)),
                sum((z[2] * z[3] for z in v if z[4] == 'true'), D(0)))
    buy, sell = flow(aw)
    assert (buy, sell) == flow(rw)
    imbalance = D(side) * (buy - sell) / (buy + sell)
    assert len(aw) >= 3 and imbalance >= D('.10') and side * (ar[2] - upper) > 0
    expected = x['one_second']
    assert expected['cross_ts'] == ac[0] and D(expected['cross_price']) == ac[2]
    assert expected['reference_ts'] == ar[0] and D(expected['reference_price']) == ar[2]
    assert expected['aggregate_count'] == len(aw) and expected['raw_count'] == len(rw)
    assert D(expected['buy']) == buy and D(expected['sell']) == sell and D(expected['imbalance']) == imbalance
    spec = json.loads(e['long_spec'])
    checks = {str(lev): manual_pre(side, float(ar[2]), ar[0], float(ac[2]), float(spec['stop_price']), float(e['atr']), int(e['quarter_end']), lev) for lev in (10, 20)}
    assert checks == x['prechecks'] and all(v != 'passed' for v in checks.values())
    out = {'all_checks_pass': True, 'observation_id': OBS, 'independent_archive_count': 3, 'prechecks': checks,
           'one_second_count_aggregate': len(aw), 'one_second_count_raw': len(rw),
           'one_second_buy': str(buy), 'one_second_sell': str(sell), 'one_second_imbalance': str(imbalance),
           'source_result_sha256': sha(path), 'code_sha256': sha(Path(__file__)),
           'note': 'One source repair sensitivity; remaining two cases remain unknown.'}
    (H / 'BNB独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT83_BNB_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
