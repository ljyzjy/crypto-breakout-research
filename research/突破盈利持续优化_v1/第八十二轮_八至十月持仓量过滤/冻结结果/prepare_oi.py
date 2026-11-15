"""Verify every necessary local OI point against its official daily archive."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import threading
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import requests

H = Path(__file__).resolve().parent
R81 = H.parent / '第八十一轮_八至十月一秒观察'
REF = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics')
sys.path.insert(0, str(R81))
import run_replay as runner
LOCAL = threading.local()


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def day(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m-%d')


def read_url(url, limit):
    runner.guard()
    if not hasattr(LOCAL, 'session'):
        LOCAL.session = requests.Session()
    with LOCAL.session.get(url, stream=True, timeout=(15, 60)) as r:
        r.raise_for_status()
        body = bytearray()
        for chunk in r.iter_content(65536):
            runner.guard()
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError('response_too_large')
        return bytes(body)


def archive(spec):
    symbol, date = spec
    name = f'{symbol}-metrics-{date}.zip'
    url = f'https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{name}'
    last = ''
    for _ in range(3):
        try:
            parts = read_url(url + '.CHECKSUM', 4096).decode().strip().split()
            assert len(parts) >= 2 and re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]) and Path(parts[1]).name == name
            body = read_url(url, 2_000_000)
            digest = hashlib.sha256(body).hexdigest()
            assert digest == parts[0].lower()
            values = {}
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                assert z.namelist() == [name.replace('.zip', '.csv')]
                with io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig', newline='') as f:
                    for row in csv.DictReader(f):
                        assert row['symbol'] == symbol
                        dt = datetime.fromisoformat(row['create_time'])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        ts = int(dt.timestamp() * 1000)
                        assert day(ts) == date and ts % 300000 == 0
                        value = Decimal(row['sum_open_interest'])
                        assert value.is_finite()
                        values.setdefault(ts, []).append(str(value))
            return {'symbol': symbol, 'day': date, 'status': 'verified', 'sha256': digest,
                    'bytes': len(body), 'url': url, 'values': values}
        except Exception as exc:
            last = type(exc).__name__ + ':' + str(exc)[:140]
            if 'headroom' in last or '404' in last:
                break
    return {'symbol': symbol, 'day': date, 'status': 'unknown', 'error': last, 'values': {}}


def main():
    runner.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, digest in frozen['prior_inputs_sha256'].items():
        assert sha(R81 / name) == digest
    audit = json.loads((R81 / '风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    summary = json.loads((R81 / '八至十月汇总独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass'] and audit['ledger_sha256'] == frozen['prior_inputs_sha256']['一秒回放批次/动态池单位收益与风险.parquet']
    assert summary['all_checks_pass'] and summary['result_sha256'] == sha(R81 / '八至十月一秒观察结果.json')
    ledger = pq.read_table(R81 / '一秒回放批次/动态池单位收益与风险.parquet').to_pylist()
    events = {}
    for row in ledger:
        if row['status'] != 'verified' or row['risk_status'] != 'verified' or row['liq_proxy'] is not False:
            continue
        obs, decision = row['observation_id'], int(row['decision_ts'])
        now = ((decision - 900000) // 300000) * 300000
        assert 900000 <= decision - now < 1200000
        value = {'observation_id': obs, 'decision_ts': decision, 'oi_t0': now, 'oi_previous': now - 3600000}
        if obs in events:
            assert events[obs] == value
        events[obs] = value
    required = {(s, e[k]) for e in events.values() for s in ('BTCUSDT', 'ETHUSDT') for k in ('oi_t0', 'oi_previous')}
    local = {}
    for sym in ('BTCUSDT', 'ETHUSDT'):
        path = REF / f'{sym}-metrics-5m.parquet'
        assert sha(path) == frozen['local_metrics_sha256'][sym]
        needed = np.array(sorted(t for s, t in required if s == sym), dtype=np.int64)
        table = pq.ParquetFile(path)
        for batch in table.iter_batches(columns=['sum_open_interest', 'ts'], batch_size=8192, use_threads=False):
            runner.guard()
            times = batch.column(1).cast(pa.int64()).to_numpy(zero_copy_only=False) // 1000
            vals = batch.column(0).to_numpy(zero_copy_only=False)
            for i in np.flatnonzero(np.isin(times, needed)):
                v = float(vals[i])
                local.setdefault((sym, int(times[i])), []).append(str(v) if math.isfinite(v) else None)
    specs = sorted({(s, day(t)) for s, t in required})
    downloaded = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(archive, spec): spec for spec in specs}
        for i, future in enumerate(as_completed(jobs), 1):
            downloaded[jobs[future]] = future.result()
            if i % 8 == 0 or i == len(jobs):
                print('EXT82_OI_SOURCE', i, '/', len(jobs), 'unknown', sum(x['status'] != 'verified' for x in downloaded.values()), flush=True)
    points = []
    for sym, ts in sorted(required):
        item = downloaded[(sym, day(ts))]
        raw, loc = item['values'].get(ts, []), local.get((sym, ts), [])
        valid = (item['status'] == 'verified' and len(raw) == len(loc) == 1 and loc[0] is not None and
                 Decimal(raw[0]).is_finite() and Decimal(raw[0]) > 0 and Decimal(raw[0]) == Decimal(loc[0]))
        points.append({'symbol': sym, 'ts': ts, 'official_values': raw, 'local_values': loc,
                       'status': 'verified' if valid else 'unknown', 'archive_sha256': item.get('sha256')})
    metadata = [{k: v for k, v in rec.items() if k != 'values'} for rec in downloaded.values()]
    out = {'events': list(events.values()), 'points': points, 'archive_metadata': metadata,
           'point_counts': {'required': len(points), 'verified': sum(x['status'] == 'verified' for x in points)},
           'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
           'risk_audit_sha256': sha(R81 / '风险来源与账本独立核验.json'),
           'note': 'Public/local source agreement only; actual historical live publication delay unknown.'}
    (H / '持仓量逐点来源核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT82_OI_PREPARED', len(events), out['point_counts'], flush=True)


if __name__ == '__main__':
    main()
