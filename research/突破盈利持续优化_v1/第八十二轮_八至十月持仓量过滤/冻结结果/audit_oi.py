"""Independently re-download all official OI archives and check all points."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests

H = Path(__file__).resolve().parent
R81 = H.parent / '第八十一轮_八至十月一秒观察'
REF = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics')
sys.path.insert(0, str(R81))
import run_replay as runner


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def fetch(meta):
    for attempt in range(3):
        try:
            runner.guard()
            with requests.Session() as s:
                c = s.get(meta['url'] + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
                parts = c.text.split()
                assert parts[0].lower() == meta['sha256'] and Path(parts[1]).name == Path(meta['url']).name
                r = s.get(meta['url'], timeout=(15, 60)); r.raise_for_status()
                body = r.content
            assert len(body) == meta['bytes'] and hashlib.sha256(body).hexdigest() == meta['sha256']
            frame = pd.read_csv(io.BytesIO(body), compression='zip', dtype=str)
            assert frame.symbol.eq(meta['symbol']).all()
            dates = pd.to_datetime(frame.create_time, utc=True)
            assert dates.dt.strftime('%Y-%m-%d').eq(meta['day']).all()
            times = (dates.astype('datetime64[ns, UTC]').astype('int64') // 1_000_000).to_numpy(dtype=np.int64)
            assert (times % 300000 == 0).all()
            out = {}
            for t, val in zip(times, frame.sum_open_interest):
                out.setdefault(int(t), []).append(str(Decimal(val)))
            return (meta['symbol'], meta['day']), out
        except requests.exceptions.RequestException as exc:
            if attempt == 2:
                raise
            print('EXT82_OI_AUDIT_RETRY', meta['symbol'], meta['day'], type(exc).__name__, flush=True)
            time.sleep(attempt + 1)


def main():
    runner.guard(start=True)
    path = H / '持仓量逐点来源核验.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert result['frozen_sha256'] == sha(H / '冻结时点.json') and result['code_sha256'] == sha(H / 'prepare_oi.py')
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for name, value in frozen['prior_inputs_sha256'].items():
        assert sha(R81 / name) == value
    events = {e['observation_id']: e for e in result['events']}
    ledger = pq.read_table(R81 / '一秒回放批次/动态池单位收益与风险.parquet').to_pylist()
    eligible = {(x['observation_id'], int(x['decision_ts'])) for x in ledger if x['status'] == x['risk_status'] == 'verified' and x['liq_proxy'] is False}
    assert eligible == {(e['observation_id'], e['decision_ts']) for e in events.values()}
    for e in events.values():
        decision = e['decision_ts']
        assert e['oi_t0'] == ((decision - 900000) // 300000) * 300000
        assert 900000 <= decision - e['oi_t0'] < 1200000 and e['oi_previous'] == e['oi_t0'] - 3600000
    # At the 5-minute boundary and one millisecond before it, no later point is eligible.
    assert ((1800000 - 900000) // 300000) * 300000 == 900000
    assert ((1799999 - 900000) // 300000) * 300000 == 600000
    points = {(p['symbol'], int(p['ts'])): p for p in result['points']}
    required = {(s, e[k]) for e in events.values() for s in ('BTCUSDT', 'ETHUSDT') for k in ('oi_t0', 'oi_previous')}
    assert set(points) == required and len(points) == len(result['points'])
    archives = [x for x in result['archive_metadata'] if x['status'] == 'verified']
    loaded = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(fetch, item) for item in archives]
        for i, job in enumerate(as_completed(jobs), 1):
            key, vals = job.result()
            loaded[key] = vals
            if i % 8 == 0 or i == len(jobs):
                print('EXT82_INDEPENDENT_OI_ARCHIVE', i, '/', len(jobs), flush=True)
    for sym in ('BTCUSDT', 'ETHUSDT'):
        path_local = REF / f'{sym}-metrics-5m.parquet'
        assert sha(path_local) == frozen['local_metrics_sha256'][sym]
        frame = pq.read_table(path_local, columns=['ts', 'sum_open_interest']).to_pandas(ignore_metadata=True)
        times = pd.to_datetime(frame.ts, utc=True).astype('datetime64[ns, UTC]').astype('int64') // 1_000_000
        wanted = {t for s, t in required if s == sym}
        frame = frame[np.isin(times.to_numpy(), list(wanted))].copy()
        frame['ms'] = times.loc[frame.index]
        local = {}
        for row in frame.itertuples(index=False):
            local.setdefault(int(row.ms), []).append(str(float(row.sum_open_interest)))
        for s, ts in required:
            if s != sym:
                continue
            p = points[(sym, ts)]
            date = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m-%d')
            official = loaded.get((sym, date), {}).get(ts, [])
            vals = local.get(ts, [])
            assert p['official_values'] == official and p['local_values'] == vals
            valid = len(official) == len(vals) == 1 and Decimal(official[0]) > 0 and Decimal(official[0]) == Decimal(vals[0])
            assert p['status'] == ('verified' if valid else 'unknown')
    out = {'all_checks_pass': True, 'events_checked': len(events), 'points_checked': len(points),
           'official_archives_redownloaded': len(archives), 'verified_points': sum(p['status'] == 'verified' for p in points.values()),
           'source_sha256': sha(H / '持仓量逐点来源核验.json'), 'code_sha256': sha(Path(__file__)),
           'note': 'Source and causal timestamp audit; historical publication latency is not verified.'}
    (H / '持仓量逐点独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT82_OI_INDEPENDENT_PASS', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
