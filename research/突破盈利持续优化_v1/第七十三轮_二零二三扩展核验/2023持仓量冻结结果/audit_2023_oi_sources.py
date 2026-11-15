"""Independently re-read all required OI points and the sampled official ZIPs."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import time
import urllib.request
import zipfile

import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

H = Path(__file__).resolve().parent
ROOT = H.parent.parent.parent
REF = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics')


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError('disk_headroom')
    while psutil.virtual_memory().available < 650 * 1024 ** 2:
        if shutil.disk_usage(ROOT).free < 2_200_000_000:
            raise RuntimeError('disk_headroom')
        time.sleep(3)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            guard()
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def day(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m-%d')


def get(url, limit):
    guard()
    with urllib.request.urlopen(url, timeout=45) as r:
        body = r.read(limit + 1)
    if len(body) > limit:
        raise ValueError('response_too_large')
    return body


def main():
    path = H / '2023持仓量逐点核验.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    assert source['plan_sha256'] == sha(H / '冻结研究方案.md') and source['code_sha256'] == sha(H / 'prepare_2023_oi.py')
    points = {(x['symbol'], int(x['ts'])): x for x in source['points']}
    assert len(points) == len(source['points'])
    seen = defaultdict(list)
    for sym in ('BTCUSDT', 'ETHUSDT'):
        file = REF / f'{sym}-metrics-5m.parquet'
        assert sha(file) == source['source_parquet_sha256'][sym]
        wanted = {ts for s, ts in points if s == sym}
        for batch in pq.ParquetFile(file).iter_batches(columns=['ts', 'sum_open_interest'], batch_size=8192, use_threads=False):
            guard()
            times = batch.column(0).cast(pa.int64()).to_numpy(zero_copy_only=False) // 1000
            values = batch.column(1).to_numpy(zero_copy_only=False)
            for i in np.flatnonzero(np.isin(times, list(wanted))):
                v = float(values[i])
                seen[(sym, int(times[i]))].append(v if math.isfinite(v) else None)
    bad_days = {(x['symbol'], x['day']) for x in source['official_errors']}
    for key, point in points.items():
        actual = seen[key]
        assert actual == point['values']
        if point['status'] == 'verified':
            assert len(actual) == 1 and actual[0] is not None and actual[0] > 0 and (key[0], day(key[1])) not in bad_days
        elif point['status'] == 'missing_or_duplicate':
            assert len(actual) != 1
        elif point['status'] == 'invalid_value':
            assert len(actual) == 1 and (actual[0] is None or actual[0] <= 0)
        elif point['status'] == 'official_sample_unavailable':
            assert (key[0], day(key[1])) in bad_days
        else:
            raise AssertionError('unknown point status')
    official_checks = 0
    for archive in source['official_daily_archives']:
        body = get(archive['url'], 2_000_000)
        assert hashlib.sha256(body).hexdigest() == archive['sha256'] and len(body) == archive['bytes']
        expected = {ts: p for (sym, ts), p in points.items() if sym == archive['symbol'] and day(ts) == archive['day']}
        found = {}
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            members = [n for n in z.namelist() if not n.endswith('/')]
            assert len(members) == 1
            with io.TextIOWrapper(z.open(members[0]), encoding='utf-8-sig', newline='') as f:
                for row in csv.DictReader(f):
                    dt = datetime.fromisoformat(row['create_time'])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts = int(dt.timestamp() * 1000)
                    if ts in expected:
                        assert ts not in found and row['symbol'] == archive['symbol']
                        found[ts] = Decimal(row['sum_open_interest'])
        for ts, point in expected.items():
            if point['status'] == 'verified':
                assert ts in found and Decimal(str(point['values'][0])) == found[ts]
                official_checks += 1
    result = {'all_checks_pass': True, 'points_checked': len(points), 'official_archives_rechecked': len(source['official_daily_archives']),
              'sample_points_compared': official_checks, 'original_sample_errors': source['official_errors'],
              'point_input_sha256': sha(path), 'audit_code_sha256': sha(Path(__file__)),
              'note': 'All required local points and available sampled official archives checked; live release times are not established.'}
    (H / '2023持仓量来源独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('YEAR2023_OI_SOURCE_AUDIT', len(points), len(source['official_daily_archives']), official_checks, flush=True)


if __name__ == '__main__':
    main()
