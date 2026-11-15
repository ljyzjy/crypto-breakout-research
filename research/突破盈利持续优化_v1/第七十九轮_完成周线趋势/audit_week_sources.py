"""Independent full source, timestamp, and price audit before evaluating week rules."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import threading
import zipfile

import psutil
import pyarrow as pa
import pyarrow.parquet as pq
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
LOCAL = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\perp')
W, DAY, HR, MON = 604800000, 86400000, 3600000, 345600000
CTX = threading.local()


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 300 * 1024**2:
        raise RuntimeError('disk_or_memory_headroom')


def get(url, limit):
    guard()
    if not hasattr(CTX, 'session'):
        CTX.session = requests.Session()
    with CTX.session.get(url, stream=True, timeout=(15, 60)) as res:
        res.raise_for_status()
        body = bytearray()
        for chunk in res.iter_content(65536):
            guard()
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError('archive_too_large')
        return bytes(body)


def fetch(a):
    checksum = get(a['url'] + '.CHECKSUM', 4096).decode().strip().split()
    assert len(checksum) >= 2 and checksum[0].lower() == a['sha256']
    assert Path(checksum[1]).name == Path(a['url']).name
    body = get(a['url'], 2_000_000)
    assert len(body) == a['bytes'] and hashlib.sha256(body).hexdigest() == a['sha256']
    result = {}
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        assert len(names) == 1 and names[0] == Path(a['url']).name.replace('.zip', '.csv')
        with io.TextIOWrapper(archive.open(names[0]), encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                start, end = int(row['open_time']), int(row['close_time'])
                span = W if a['interval'] == '1w' else DAY
                assert end == start + span - 1 and start not in result
                assert datetime.fromtimestamp(start / 1000, timezone.utc).strftime('%Y-%m') == a['month']
                assert ((start - MON) % W == 0 if span == W else start % DAY == 0)
                vals = {key: Decimal(row[key]) for key in ('open', 'high', 'low', 'close')}
                assert all(v.is_finite() and v > 0 for v in vals.values())
                assert vals['low'] <= min(vals.values()) <= max(vals.values()) <= vals['high']
                result[start] = vals
    return (a['symbol'], a['month'], a['interval']), result


def main():
    prep_path = HERE / '已完成周线来源核验.json'
    prep = json.loads(prep_path.read_text(encoding='utf-8'))
    assert prep['plan_sha256'] == digest(HERE / '冻结研究方案.md')
    assert prep['amendment_sha256'] == digest(HERE / '周线缺口补充规则.md')
    assert prep['frozen_sha256'] == digest(HERE / '冻结时点.json')
    assert prep['code_sha256'] == digest(HERE / 'prepare_weeks.py')
    frozen = json.loads((HERE / '冻结时点.json').read_text(encoding='utf-8'))
    events = {(e['year'], e['observation_id']): e for e in prep['events']}
    assert len(events) == len(prep['events']) == 98
    # Independently trace event IDs, side and decision time to immutable original ledgers.
    found = {}
    for year in ('2023', '2024', '2026'):
        base = HERE.parent / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
        manifest = base / '完整快照哈希.json'
        assert digest(manifest) == frozen['base_snapshots'][year]
        meta = json.loads(manifest.read_text(encoding='utf-8'))
        path = base / 'batch/动态池单位收益与风险.parquet'
        assert digest(path) == meta['files']['batch/动态池单位收益与风险.parquet']
        for r in pq.read_table(path, columns=['observation_id', 'status', 'risk_status', 'liq_proxy', 'decision_ts', 'side']).to_pylist():
            if r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False:
                key = (year, r['observation_id'])
                e = events[key]
                assert e['decision_ts'] == int(r['decision_ts']) and e['side'] == int(r['side'])
                last = ((e['decision_ts'] - MON) // W) * W + MON - W
                assert e['last_week_start'] == last and last + W <= e['decision_ts'] < last + 2 * W
                found[key] = e
    assert found == events
    weeks = {(r['symbol'], r['week_start']): r for r in prep['weeks']}
    assert len(weeks) == len(prep['weeks']) == 292
    required = {(s, e['last_week_start'] - i * W) for e in events.values() for s in ('BTCUSDT', 'ETHUSDT') for i in range(29)}
    assert set(weeks) == required
    source_hashes = {h for w in weeks.values() for h in w['source_sha256']}
    archives = [a for a in prep['official_archives'] if a['status'] == 'verified' and a['sha256'] in source_hashes]
    assert source_hashes == {a['sha256'] for a in archives}
    source = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(fetch, a) for a in archives]
        for i, job in enumerate(as_completed(jobs), 1):
            key, value = job.result()
            assert key not in source
            source[key] = value
            if i % 10 == 0 or i == len(jobs):
                print('INDEPENDENT_WEEK_SOURCE', i, '/', len(jobs), flush=True)
    archive_map = {(a['symbol'], a['month'], a['interval']): a for a in archives}
    mode_counts = {}
    for (symbol, start), w in weeks.items():
        assert w['status'] == 'verified' and w['week_end_exclusive'] == start + W and (start - MON) % W == 0
        mode = w['source_mode']
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        if mode == 'official_weekly':
            mon = datetime.fromtimestamp(start / 1000, timezone.utc).strftime('%Y-%m')
            key = (symbol, mon, '1w')
            value = source[key][start]
            hashes = {archive_map[key]['sha256']}
        else:
            assert mode == 'official_daily_reconstruction'
            days, hashes = [], set()
            for i in range(7):
                t = start + i * DAY
                mon = datetime.fromtimestamp(t / 1000, timezone.utc).strftime('%Y-%m')
                key = (symbol, mon, '1d')
                days.append(source[key][t])
                hashes.add(archive_map[key]['sha256'])
            value = {'open': days[0]['open'], 'high': max(d['high'] for d in days),
                     'low': min(d['low'] for d in days), 'close': days[-1]['close']}
        assert hashes == set(w['source_sha256'])
        for k in ('open', 'high', 'low', 'close'):
            # Exact Decimal check ensures no rounding can flip a strict MA comparison.
            assert value[k] == Decimal(str(w['official_ohlc'][k]))
            assert math.isclose(float(value[k]), w['local_ohlc'][k], rel_tol=1e-9, abs_tol=1e-10)
    for symbol in ('BTCUSDT', 'ETHUSDT'):
        guard()
        path = LOCAL / f'k1h_{symbol}.parquet'
        assert digest(path) == prep['local_hourly_sha256'][symbol]
        table = pq.read_table(path, columns=['dt', 'open', 'high', 'low', 'close'])
        times = table['dt'].cast(pa.int64()).to_pylist()
        vals = [table[k].to_pylist() for k in ('open', 'high', 'low', 'close')]
        assert len(set(times)) == len(times)
        lookup = {int(t): i for i, t in enumerate(times)}
        for s, start in required:
            if s != symbol:
                continue
            idx = [lookup[start + i * HR] for i in range(168)]
            local = {'open': vals[0][idx[0]], 'high': max(vals[1][i] for i in idx),
                     'low': min(vals[2][i] for i in idx), 'close': vals[3][idx[-1]]}
            for k, v in local.items():
                assert math.isclose(v, weeks[(s, start)]['local_ohlc'][k], rel_tol=1e-12, abs_tol=1e-12)
        del table, times, vals, lookup
        print('INDEPENDENT_HOURLY', symbol, sum(s == symbol for s, _ in required), flush=True)
    audit = {'all_checks_pass': True, 'events': len(events), 'symbol_weeks': len(weeks),
             'mode_counts': mode_counts, 'official_archives_redownloaded': len(archives),
             'source_sha256': digest(prep_path), 'audit_code_sha256': digest(Path(__file__)),
             'note': 'Completed-week official and hourly prices audited; actual historical publication latency not established.'}
    (HERE / '已完成周线独立核验.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('INDEPENDENT_WEEK_AUDIT', audit, flush=True)


if __name__ == '__main__':
    main()
