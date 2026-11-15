"""Re-download risk archives and independently verify cached rows and ledger math."""
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
B = H / '一秒回放批次'
import run_replay as runner

M = 60000
BASE = 'https://data.binance.vision/data/futures/um/monthly/'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def fetch(info):
    kind, sym, mon = info['kind'], info['contract'], info['month']
    name = f'{sym}-1m-{mon}.zip' if kind == 'markPriceKlines' else f'{sym}-fundingRate-{mon}.zip'
    suffix = f'{kind}/{sym}/1m/{name}' if kind == 'markPriceKlines' else f'{kind}/{sym}/{name}'
    url = BASE + suffix
    for attempt in range(3):
        try:
            runner.guard()
            with requests.Session() as s:
                check = s.get(url + '.CHECKSUM', timeout=(15, 50)); check.raise_for_status()
                parts = check.text.split()
                assert parts[0].lower() == info['sha256'] and Path(parts[1]).name == name
                r = s.get(url, timeout=(15, 90)); r.raise_for_status()
                body = r.content
            assert len(body) == info['bytes'] and hashlib.sha256(body).hexdigest() == info['sha256']
            frame = pd.read_csv(io.BytesIO(body), compression='zip')
            cols = ['open_time', 'open', 'high', 'low', 'close'] if kind == 'markPriceKlines' else ['calc_time', 'funding_interval_hours', 'last_funding_rate']
            frame = frame[cols].apply(pd.to_numeric, errors='raise').rename(columns={'open_time': 'ts', 'calc_time': 'ts'})
            assert not frame.ts.duplicated().any() and np.isfinite(frame.to_numpy(float)).all()
            return frame.set_index('ts')
        except requests.exceptions.RequestException as exc:
            if attempt == 2:
                raise
            print('EXT81_RISK_AUDIT_RETRY', kind, sym, mon, type(exc).__name__, flush=True)
            time.sleep(attempt + 1)


def main():
    runner.guard(start=True)
    source = json.loads((B / '风险来源与结算.json').read_text(encoding='utf-8'))
    assert source['code_sha256'] == sha(H / 'settle_risk.py')
    assert source['source_engine_sha256'] == sha(H.parent / '第三十三轮_动态池逐笔执行/settle_dynamic_paths.py')
    assert source['signal_sha256'] == sha(B / '动态池逐笔信号筛查.parquet')
    assert source['paths_sha256'] == sha(B / '动态池延迟市价路径.parquet')
    assert source['ledger_sha256'] == sha(B / '动态池单位收益与风险.parquet')
    marks, funds, checked_sources, unknown_sources = {}, {}, 0, 0
    for info in source['sources']:
        if info['status'] != 'verified':
            unknown_sources += 1
            continue
        cache_path = Path(info['cache_path'])
        assert sha(cache_path) == info['cache_sha256']
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        assert cache['status'] == 'verified' and cache['sha256'] == info['sha256']
        frame = fetch(info)
        expected_cols = ['open', 'high', 'low', 'close'] if info['kind'] == 'markPriceKlines' else ['funding_interval_hours', 'last_funding_rate']
        if info['kind'] == 'fundingRate':
            assert len(frame) == len(cache['rows'])
        for row in cache['rows']:
            assert int(row['ts']) in frame.index
            actual = frame.loc[int(row['ts'])]
            assert all(near(actual[k], row[k]) for k in expected_cols)
            if info['kind'] == 'markPriceKlines':
                marks[(info['contract'], int(row['ts']))] = row
        if info['kind'] == 'fundingRate':
            funds[(info['contract'], info['month'])] = cache['rows']
        checked_sources += 1
        print('EXT81_RISK_AUDIT_SOURCE', checked_sources, '/', len(source['sources']), info['kind'], info['contract'], info['month'], flush=True)
    ledger = pd.read_parquet(B / '动态池单位收益与风险.parquet')
    checked, maxerr = 0, 0.0
    for r in ledger.itertuples(index=False):
        if r.risk_status != 'verified':
            continue
        side, lev = int(r.side), int(r.variant.rsplit('_', 1)[1].rstrip('x'))
        entry, exit_ = float(r.entry_raw) * (1 + side * .0005), float(r.exit_raw) * (1 - side * .0005)
        assert near(entry, r.entry_fill) and near(exit_, r.exit_fill)
        assert r.entry_signal_reference_ts >= r.decision_ts + 1000 and r.entry_ts >= r.entry_signal_reference_ts + 1000
        assert r.exit_ts >= r.exit_signal_ts + 5000
        qty, funding, extremes, events = 1 / entry, 0.0, [], []
        for ts in range(int(r.entry_ts) // M * M, int(r.exit_ts) // M * M + M, M):
            mark = marks[(r.contract, ts)]
            extremes.append(float(mark['low'] if side == 1 else mark['high']))
            mon = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m')
            rows = sorted(funds[(r.contract, mon)], key=lambda x: x['ts'])
            assert rows
            before = [x for x in rows if x['ts'] <= ts]
            after = [x for x in rows if x['ts'] > ts]
            lo = before[-1] if before else rows[0]
            hi = after[0] if after else rows[-1]
            allowance = max(lo['funding_interval_hours'], hi['funding_interval_hours']) * 3600000 * 1.5
            gap = hi['ts'] - lo['ts'] if before and after else (rows[0]['ts'] - ts if not before else ts - rows[-1]['ts'])
            assert gap <= allowance
            for x in rows:
                ft = int(x['ts'])
                if ft // M * M != ts or not r.entry_ts <= ft <= r.exit_ts:
                    continue
                amount = side * qty * float(mark['open']) * float(x['last_funding_rate'])
                funding += max(0.0, amount) if ft in (r.entry_ts, r.exit_ts) else amount
                events.append(ft)
        assert near(funding, r.funding) and sorted(events) == sorted(int(x['settlement_ts']) for x in json.loads(r.funding_events_json))
        net = side * qty * (exit_ - entry) - .0005 - qty * exit_ * .0005 - funding
        assert near(net, r.net_per_unit_notional) and near(r.entry_fee, .0005) and near(r.exit_fee, qty * exit_ * .0005)
        proxy = any(1 / lev - .0005 - max(funding, 0) + side * qty * (v - entry) <= qty * v * .01 for v in extremes)
        assert proxy == bool(r.liq_proxy)
        checked += 1
        maxerr = max(maxerr, abs(net - r.net_per_unit_notional))
    out = {'all_checks_pass': True, 'verified_source_archives_redownloaded': checked_sources, 'unknown_source_archives': unknown_sources,
           'risk_paths_independently_checked': checked, 'maximum_net_fraction_error': maxerr,
           'input_sha256': sha(B / '风险来源与结算.json'), 'ledger_sha256': sha(B / '动态池单位收益与风险.parquet'),
           'code_sha256': sha(Path(__file__)), 'note': 'Audits verified rows; missing sources stay unknown; no real exchange liquidation.'}
    (H / '风险来源与账本独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT81_RISK_AUDIT_PASS', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
