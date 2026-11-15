"""Independently re-read all mark/funding archives and verify both paired paths."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import requests

H = Path(__file__).resolve().parent
P = H.parent
sys.path.insert(0, str(P / '第八十一轮_八至十月一秒观察'))
import run_replay as guardlib

M = 60000
BASE = 'https://data.binance.vision/data/futures/um/monthly/'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def fetch(info):
    kind, symbol, mon = info['kind'], info['contract'], info['month']
    name = f'{symbol}-1m-{mon}.zip' if kind == 'markPriceKlines' else f'{symbol}-fundingRate-{mon}.zip'
    sub = f'{kind}/{symbol}/1m/{name}' if kind == 'markPriceKlines' else f'{kind}/{symbol}/{name}'
    url = BASE + sub
    for attempt in range(3):
        try:
            guardlib.guard()
            with requests.Session() as s:
                c = s.get(url + '.CHECKSUM', timeout=(15, 50)); c.raise_for_status()
                parts = c.text.split()
                assert parts[0].lower() == info['sha256'] and Path(parts[1]).name == name
                r = s.get(url, timeout=(15, 90)); r.raise_for_status()
                body = r.content
            assert len(body) == info['bytes'] and hashlib.sha256(body).hexdigest() == info['sha256']
            frame = pd.read_csv(io.BytesIO(body), compression='zip')
            cols = ['open_time', 'open', 'high', 'low', 'close'] if kind == 'markPriceKlines' else ['calc_time', 'funding_interval_hours', 'last_funding_rate']
            frame = frame[cols].apply(pd.to_numeric, errors='raise').rename(columns={'open_time': 'ts', 'calc_time': 'ts'})
            assert not frame.ts.duplicated().any() and np.isfinite(frame.to_numpy(float)).all()
            return (info['period'], kind, symbol, mon), frame.set_index('ts')
        except requests.exceptions.RequestException as exc:
            if attempt == 2:
                raise
            print('EXT88_AUDIT_RETRY', kind, symbol, mon, type(exc).__name__, flush=True)
            time.sleep(attempt + 1)


def check_path(contract, side, lev, path, expected, marks, funds):
    entry_ts, exit_ts = int(path['entry_ts']), int(path['exit_ts'])
    entry, exit_ = float(path['entry_fill']), float(path['exit_fill'])
    assert entry_ts <= exit_ts and int(path['exit_ts']) >= int(path['exit_signal_ts']) + 5000
    assert near(entry, float(path['entry_raw']) * (1 + side * .0005))
    assert near(exit_, float(path['exit_raw']) * (1 - side * .0005))
    funding, extremes, events = 0.0, [], []
    for ts in range(entry_ts // M * M, exit_ts // M * M + M, M):
        mark = marks[(contract, ts)]
        extremes.append(float(mark['low'] if side == 1 else mark['high']))
        mon = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')
        fr = sorted(funds[(contract, mon)], key=lambda x: x['ts'])
        assert fr
        before, after = [x for x in fr if x['ts'] <= ts], [x for x in fr if x['ts'] > ts]
        lo, hi = before[-1] if before else fr[0], after[0] if after else fr[-1]
        allowance = max(lo['funding_interval_hours'], hi['funding_interval_hours']) * 3600000 * 1.5
        gap = hi['ts'] - lo['ts'] if before and after else (fr[0]['ts'] - ts if not before else ts - fr[-1]['ts'])
        assert gap <= allowance
        for r in fr:
            ft = int(r['ts'])
            if ft // M * M != ts or not entry_ts <= ft <= exit_ts:
                continue
            amt = side / entry * float(mark['open']) * float(r['last_funding_rate'])
            funding += max(0.0, amt) if ft in (entry_ts, exit_ts) else amt
            events.append(ft)
    net = side * (exit_ - entry) / entry - .0005 - .0005 * exit_ / entry - funding
    proxy = any(1 / lev - .0005 - max(funding, 0) + side / entry * (v - entry) <= v / entry * .01 for v in extremes)
    assert near(expected['funding'], funding) and near(expected['net_per_unit_notional'], net)
    assert sorted(events) == sorted(int(x['settlement_ts']) for x in json.loads(expected['funding_events_json']))
    assert bool(expected['liq_proxy']) == proxy is False
    return net


def main():
    guardlib.guard(start=True)
    path = H / '延长持有风险账本.json'
    source = json.loads(path.read_text(encoding='utf-8'))
    assert source['code_sha256'] == sha(H / 'settle_extension.py') and source['risk_engine_sha256'] == sha(P / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py')
    assert source['inputs_sha256'] == sha(H / '原柱末退出回放输入.json') and source['progress_sha256'] == sha(H / '延长持有逐笔进度.json')
    valid = [x for x in source['risk_archives'] if x['status'] == 'verified']
    reloaded = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(fetch, x) for x in valid]
        for i, job in enumerate(as_completed(jobs), 1):
            key, frame = job.result()
            assert key not in reloaded
            reloaded[key] = frame
            if i % 10 == 0 or i == len(jobs):
                print('EXT88_RISK_INDEPENDENT_SOURCE', i, '/', len(jobs), flush=True)
    marks, funds = {}, {}
    for info in valid:
        cache = Path(info['cache_path'])
        assert sha(cache) == info['cache_sha256']
        x = json.loads(cache.read_text(encoding='utf-8'))
        assert x['status'] == 'verified' and x['sha256'] == info['sha256']
        key = info['period'], info['kind'], info['contract'], info['month']
        frame = reloaded[key]
        cols = ['open', 'high', 'low', 'close'] if info['kind'] == 'markPriceKlines' else ['funding_interval_hours', 'last_funding_rate']
        if info['kind'] == 'fundingRate':
            assert len(frame) == len(x['rows'])
        for row in x['rows']:
            assert int(row['ts']) in frame.index
            assert all(near(frame.loc[int(row['ts'])][k], row[k]) for k in cols)
            if info['kind'] == 'markPriceKlines': marks[(info['period'], info['contract'], int(row['ts']))] = row
        if info['kind'] == 'fundingRate': funds[(info['period'], info['contract'], info['month'])] = x['rows']
    for record in source['records']:
        period, symbol, side = record['period'], record['contract'], int(record['side'])
        lev = int(record['variant'].rsplit('_', 1)[1].rstrip('x'))
        local_marks = {(s, ts): x for (p, s, ts), x in marks.items() if p == period and s == symbol}
        local_funds = {(s, mon): x for (p, s, mon), x in funds.items() if p == period and s == symbol}
        check_path(symbol, side, lev, record['original'], record['original'], local_marks, local_funds)
        check_path(symbol, side, lev, record['extended'], record['risk'], local_marks, local_funds)
    out = {'all_checks_pass': True, 'paired_paths_checked': len(source['records']),
           'unknown_paths_preserved': len(source['unknown']), 'risk_archives_redownloaded': len(valid),
           'source_sha256': sha(path), 'code_sha256': sha(Path(__file__)),
           'note': 'Independent risk and fee arithmetic on known paths; unverified or proxy-liquidation paths stay unknown.'}
    (H / '延长持有风险独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT88_RISK_AUDIT', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
