"""Verify all required completed BTC/ETH weeks against official and hourly sources."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import threading
import time
import zipfile

import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
import requests

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
REF = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\perp')
W, D, HOUR, MONDAY = 604800000, 86400000, 3600000, 345600000
LOCAL = threading.local()


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available < 300 * 1024 ** 2:
        raise RuntimeError('memory_headroom')


def week_start(ts):
    return ((int(ts) - MONDAY) // W) * W + MONDAY


def ym(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')


def session():
    if not hasattr(LOCAL, 'session'):
        LOCAL.session = requests.Session()
    return LOCAL.session


def get(url, limit):
    guard()
    with session().get(url, stream=True, timeout=(10, 45)) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(65536):
            guard()
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError('response_too_large')
        return bytes(body)


def archive(spec):
    symbol, mon, interval = spec
    name = f'{symbol}-{interval}-{mon}.zip'
    url = f'https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{interval}/{name}'
    error = ''
    for attempt in range(2):
        try:
            parts = get(url + '.CHECKSUM', 4096).decode('utf-8').strip().split()
            assert len(parts) >= 2 and re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]) and Path(parts[1]).name == name
            body = get(url, 2_000_000)
            digest = hashlib.sha256(body).hexdigest()
            assert digest == parts[0].lower()
            records = {}
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                files = [n for n in z.namelist() if not n.endswith('/')]
                assert files == [name.replace('.zip', '.csv')]
                with io.TextIOWrapper(z.open(files[0]), encoding='utf-8-sig', newline='') as stream:
                    for row in csv.DictReader(stream):
                        ts, end = int(row['open_time']), int(row['close_time'])
                        duration = W if interval == '1w' else D
                        assert ts not in records and end == ts + duration - 1 and ym(ts) == mon
                        assert (week_start(ts) == ts if interval == '1w' else ts % D == 0)
                        values = {k: float(row[k]) for k in ('open', 'high', 'low', 'close')}
                        assert all(math.isfinite(v) and v > 0 for v in values.values())
                        assert values['low'] <= min(values['open'], values['close'], values['high'])
                        assert values['high'] >= max(values['open'], values['close'], values['low'])
                        records[ts] = {'open_time': ts, 'close_time': end, **values}
            return {'symbol': symbol, 'month': mon, 'interval': interval, 'status': 'verified', 'sha256': digest,
                    'bytes': len(body), 'url': url, 'rows': records}
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)[:140]
            if 'headroom' in error or isinstance(exc, requests.HTTPError) and getattr(exc.response, 'status_code', None) == 404:
                break
            if attempt == 0:
                time.sleep(1)
    return {'symbol': symbol, 'month': mon, 'interval': interval, 'status': 'unknown', 'error': error, 'rows': {}}


def load_events(frozen):
    events = {}
    for year in ('2023', '2024', '2026'):
        base = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
        manifest_path = base / '完整快照哈希.json'
        assert sha(manifest_path) == frozen['base_snapshots'][year]
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        path = base / 'batch/动态池单位收益与风险.parquet'
        assert sha(path) == manifest['files']['batch/动态池单位收益与风险.parquet']
        for row in pq.read_table(path, columns=['observation_id', 'status', 'risk_status', 'liq_proxy', 'decision_ts', 'side']).to_pylist():
            if row['status'] != 'verified' or row['risk_status'] != 'verified' or row['liq_proxy'] is not False:
                continue
            obs, ts, side = row['observation_id'], int(row['decision_ts']), int(row['side'])
            last = week_start(ts) - W
            assert last + W <= ts and side in (-1, 1)
            value = {'year': year, 'observation_id': obs, 'decision_ts': ts, 'side': side, 'last_week_start': last}
            key = (year, obs)
            if key in events:
                assert events[key] == value
            events[key] = value
    return list(events.values())


def fetch_all(specs, label):
    out = {}
    if not specs:
        return out
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(archive, spec): spec for spec in specs}
        for i, future in enumerate(as_completed(futures), 1):
            spec = futures[future]
            out[spec] = future.result()
            if i % 10 == 0 or i == len(specs):
                print('WEEK_SOURCE', label, i, '/', len(specs), 'unknown', sum(x['status'] != 'verified' for x in out.values()), flush=True)
    return out


def main():
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    extra = json.loads((H / '补充规则冻结.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') == extra['original_plan_sha256']
    assert extra['original_freeze_sha256'] == sha(H / '冻结时点.json') and extra['amendment_sha256'] == sha(H / '周线缺口补充规则.md')
    events = load_events(frozen)
    required = {(symbol, e['last_week_start'] - i * W) for e in events for symbol in ('BTCUSDT', 'ETHUSDT') for i in range(29)}
    weekly_specs = sorted({(s, ym(ts), '1w') for s, ts in required})
    weekly = fetch_all(weekly_specs, 'weekly')
    missing = {(s, ts) for s, ts in required if ts not in weekly[(s, ym(ts), '1w')]['rows']}
    daily_specs = sorted({(s, ym(ts + i * D), '1d') for s, ts in missing for i in range(7)})
    daily = fetch_all(daily_specs, 'daily_fallback')
    local_weeks, local_hashes = {}, {}
    for symbol in ('BTCUSDT', 'ETHUSDT'):
        guard()
        path = REF / f'k1h_{symbol}.parquet'
        local_hashes[symbol] = sha(path)
        table = pq.read_table(path, columns=['dt', 'open', 'high', 'low', 'close'])
        times = table['dt'].cast(pa.int64()).to_numpy(zero_copy_only=False)
        values = np.column_stack([table[k].to_numpy(zero_copy_only=False) for k in ('open', 'high', 'low', 'close')])
        assert len(times) == len(np.unique(times)) and (times % HOUR == 0).all()
        wanted = {ts for s, ts in required if s == symbol}
        ids = np.asarray([week_start(t) for t in times], dtype=np.int64)
        for start in wanted:
            indices = np.flatnonzero(ids == start)
            order = indices[np.argsort(times[indices])]
            if len(order) != 168 or not np.array_equal(times[order], np.arange(start, start + W, HOUR)):
                local_weeks[(symbol, start)] = None
                continue
            a = values[order]
            if not np.isfinite(a).all() or not (a > 0).all() or (a[:, 1] < np.max(a[:, [0, 2, 3]], axis=1)).any() or (a[:, 2] > np.min(a[:, [0, 1, 3]], axis=1)).any():
                local_weeks[(symbol, start)] = None
                continue
            local_weeks[(symbol, start)] = {'open': float(a[0, 0]), 'high': float(np.max(a[:, 1])),
                                            'low': float(np.min(a[:, 2])), 'close': float(a[-1, 3])}
        print('WEEK_LOCAL_HOURS', symbol, len(wanted), flush=True)
    weeks = []
    for symbol, start in sorted(required):
        official = weekly[(symbol, ym(start), '1w')]['rows'].get(start)
        mode = 'official_weekly'
        used = [weekly[(symbol, ym(start), '1w')]['sha256']] if official else []
        if official is None:
            days = [daily[(symbol, ym(start + i * D), '1d')]['rows'].get(start + i * D) for i in range(7)]
            if all(days):
                official = {'open_time': start, 'close_time': start + W - 1, 'open': days[0]['open'],
                            'high': max(x['high'] for x in days), 'low': min(x['low'] for x in days), 'close': days[-1]['close']}
                mode = 'official_daily_reconstruction'
                used = sorted({daily[(symbol, ym(start + i * D), '1d')]['sha256'] for i in range(7)})
        local = local_weeks[(symbol, start)]
        status = 'verified'
        if official is None:
            status = 'official_week_unavailable'
        elif local is None:
            status = 'local_hourly_incomplete'
        elif not all(math.isclose(official[k], local[k], rel_tol=1e-9, abs_tol=1e-10) for k in ('open', 'high', 'low', 'close')):
            status = 'official_hourly_mismatch'
        weeks.append({'symbol': symbol, 'week_start': start, 'week_end_exclusive': start + W,
                      'status': status, 'source_mode': mode if official else None, 'source_sha256': used,
                      'official_ohlc': {k: official[k] for k in ('open', 'high', 'low', 'close')} if official else None,
                      'local_ohlc': local})
    archives = [{k: v for k, v in x.items() if k != 'rows'} for x in [*weekly.values(), *daily.values()]]
    out = {'all_weeks_verified': all(x['status'] == 'verified' for x in weeks), 'events': events, 'weeks': weeks,
           'week_status_counts': {s: sum(x['status'] == s for x in weeks) for s in sorted({x['status'] for x in weeks})},
           'official_archives': archives, 'weekly_missing_count': len(missing), 'local_hourly_sha256': local_hashes,
           'plan_sha256': sha(H / '冻结研究方案.md'), 'amendment_sha256': sha(H / '周线缺口补充规则.md'),
           'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Completed UTC weeks; official weekly gaps may use seven verified daily bars; no live arrival guarantee.'}
    (H / '已完成周线来源核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('WEEK_SOURCE_COMPLETE', len(events), len(weeks), out['week_status_counts'], 'weekly_gaps', len(missing), flush=True)


if __name__ == '__main__':
    main()
