"""Independent archive download and arithmetic audit for one one-second no-order."""
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import shutil
import time
import zipfile

import psutil
import requests
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
D = Decimal
OBS = 'opening|XRPUSDT|1712564100000'
START = 1712564100000


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 500 * 1024**2:
        raise RuntimeError('disk_or_memory_headroom')


def archive(item):
    for attempt in range(3):
        try:
            guard()
            with requests.Session() as s:
                check = s.get(item['url'] + '.CHECKSUM', timeout=(15, 50)); check.raise_for_status()
                parts = check.text.split()
                assert parts[0].lower() == item['sha256'] and Path(parts[1]).name == Path(item['url']).name
                response = s.get(item['url'], timeout=(15, 120)); response.raise_for_status()
                body = response.content
            assert len(body) == item['bytes'] and hashlib.sha256(body).hexdigest() == item['sha256']
            return body
        except (requests.exceptions.RequestException,) as exc:
            if attempt == 2:
                raise
            print('INDEPENDENT_XRP_RETRY', item['kind'], type(exc).__name__, flush=True)
            time.sleep(attempt + 1)


def rows(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = z.namelist()
        assert len(names) == 1 and names[0].endswith('.csv')
        with io.TextIOWrapper(z.open(names[0]), encoding='utf-8-sig', newline='') as f:
            yield from csv.DictReader(f)


def main():
    result_path = H / '单例一秒复核结果.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert result['frozen_sha256'] == sha(H / '冻结时点.json')
    assert result['code_sha256'] == sha(H / 'recheck_xrp.py') and result['observation_id'] == OBS
    assert frozen['plan_sha256'] == sha(H / '冻结方案.md')
    src = {x['kind']: x for x in result['archives']}
    assert {k: x['sha256'] for k, x in src.items()} == frozen['prior_official_archive_sha256']
    bars = [r for r in rows(archive(src['klines'])) if int(r['open_time']) == START]
    assert len(bars) == 1
    bar = bars[0]
    tapes = {}
    for kind in ('aggTrades', 'trades'):
        tapes[kind] = []
        for i, x in enumerate(rows(archive(src[kind])), 1):
            if i % 100000 == 0:
                guard()
            ts = int(x['transact_time'] if kind == 'aggTrades' else x['time'])
            if START <= ts < START + 120000:
                idx = int(x['agg_trade_id'] if kind == 'aggTrades' else x.get('id', x.get('trade_id')))
                maker = x['is_buyer_maker'].lower()
                assert maker in ('true', 'false')
                tapes[kind].append((ts, idx, D(x['price']), D(x.get('quantity', x.get('qty'))), maker))
        tapes[kind].sort(key=lambda x: (x[0], x[1]))
        print('INDEPENDENT_XRP_ARCHIVE', kind, len(tapes[kind]), flush=True)
    a, r = tapes['aggTrades'], tapes['trades']
    rm, am = [x for x in r if x[0] < START + 60000], [x for x in a if x[0] < START + 60000]
    def ohlc(xs):
        return [xs[0][2], max(x[2] for x in xs), min(x[2] for x in xs), xs[-1][2]]
    original = [D(bar[k]) for k in ('open', 'high', 'low', 'close')]
    assert ohlc(rm) == original and ohlc(am)[1:] == original[1:] and ohlc(am)[0] != original[0]
    assert len(rm) == int(bar.get('count', bar.get('number_of_trades')))
    assert abs(sum(x[3] for x in rm) - D(bar['volume'])) < D('.000001')
    assert abs(sum(x[2] * x[3] for x in rm) - D(bar['quote_volume'])) < D('.00001')
    R62 = P / '第六十二轮_一秒观察更早突破'
    base = R62 / '2024完整批次_冻结'
    assert sha(base / '完整快照哈希.json') == frozen['baseline_2024_result_sha256']
    bmeta = json.loads((base / '完整快照哈希.json').read_text(encoding='utf-8'))
    baseline_file = base / 'support/2024一秒观察对照.json'
    assert sha(baseline_file) == bmeta['files']['support/2024一秒观察对照.json']
    original_baseline = json.loads(baseline_file.read_text(encoding='utf-8'))
    input_file = R62 / '2024冻结输入/candidates.parquet'
    assert sha(input_file) == result['candidate_sha256']
    events = [x for x in pq.read_table(input_file).to_pylist() if x['observation_id'] == OBS]
    assert len(events) == 1
    e = events[0]
    upper, lower = D(str(e['upper'])), D(str(e['lower']))
    ac = next(x for x in am if x[2] > upper or x[2] < lower)
    rc = next(x for x in rm if x[2] > upper or x[2] < lower)
    assert (ac[0], ac[2]) == (rc[0], rc[2])
    side = 1 if ac[2] > upper else -1
    assert side == 1 and e['long_known_eligible'] and e['market_allowed_side'] == side
    ar = next(x for x in a if x[0] >= ac[0] + 1000)
    rr = next(x for x in r if x[0] >= ac[0] + 1000)
    assert (ar[0], ar[2]) == (rr[0], rr[2])
    aa = [x for x in a if ac[0] < x[0] < ac[0] + 1000]
    ra = [x for x in r if ac[0] < x[0] < ac[0] + 1000]
    def amounts(xs):
        return (sum((x[2] * x[3] for x in xs if x[4] == 'false'), D(0)),
                sum((x[2] * x[3] for x in xs if x[4] == 'true'), D(0)))
    buy, sell = amounts(aa)
    assert (buy, sell) == amounts(ra)
    im = D(side) * (buy - sell) / (buy + sell)
    assert len(aa) >= 3 and im < D('.10') and side * (ar[2] - upper) <= 0
    found = result['result']
    assert found['status'] == 'known_no_order_flow' and found['cross_ts'] == ac[0] and D(found['cross_price']) == ac[2]
    assert found['reference_ts'] == ar[0] and D(found['reference_price']) == ar[2] and found['reference_outside'] is False
    assert found['aggregate_count'] == len(aa) and found['raw_count'] == len(ra)
    assert D(found['buy']) == buy and D(found['sell']) == sell and D(found['imbalance']) == im
    sensitivity = []
    for lev in (10, 20):
        b = next(z for z in original_baseline['rows'] if z['leverage'] == lev)
        assert OBS in b['unknown_ids']
        x = b['one_second_observation']
        n, w, unknown = x['trades'], x['wins'], x['unknown']
        sensitivity.append({'leverage': lev, 'known_trades': n, 'net_wins': w,
                            'original_unknown': unknown, 'sensitivity_unknown': unknown - 1,
                            'original_known_no_order': b['known_no_order'], 'sensitivity_known_no_order': b['known_no_order'] + 1,
                            'original_optimistic_pct': 100 * (w + unknown) / (n + unknown),
                            'sensitivity_optimistic_pct': 100 * (w + unknown - 1) / (n + unknown - 1)})
    audit = {'all_checks_pass': True, 'result_sha256': sha(result_path), 'audit_code_sha256': sha(Path(__file__)),
             'independently_downloaded_archives': 3, 'candidate_observation_id': OBS,
             'first_second': {'aggregate_count': len(aa), 'raw_count': len(ra), 'buy': str(buy), 'sell': str(sell),
                              'imbalance': str(im), 'one_second_reference': str(ar[2]), 'breakout_level': str(upper)},
             'baseline_sensitivity': sensitivity,
             'note': 'One retrospective source reconciliation; not a change to original frozen ledger and not a new independent sample.'}
    (H / '单例一秒独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('INDEPENDENT_XRP_AUDIT', json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
