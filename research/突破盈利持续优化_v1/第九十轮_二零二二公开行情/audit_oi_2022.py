"""Independently re-fetch and recheck all 2022 open-interest points."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import replay_2022 as runner

H = Path(__file__).resolve().parent
REF = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics')
SOURCE = H.parent / '第八十二轮_八至十月持仓量过滤/audit_oi.py'


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    runner.guard(start=True)
    path = H / '持仓量逐点来源核验.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    assert result['frozen_sha256'] == sha(H / '冻结时点.json')
    assert result['code_sha256'] == sha(H / 'prepare_oi_2022.py')
    assert result['risk_audit_sha256'] == sha(H / '风险来源与账本独立核验.json')
    events = {e['observation_id']: e for e in result['events']}
    ledger = pq.read_table(H / '一秒回放批次/动态池单位收益与风险.parquet').to_pylist()
    eligible = {(r['observation_id'], int(r['decision_ts'])) for r in ledger
                if r['status'] == r['risk_status'] == 'verified' and r['liq_proxy'] is False}
    assert eligible == {(e['observation_id'], e['decision_ts']) for e in events.values()}
    for e in events.values():
        assert e['oi_t0'] == ((e['decision_ts'] - 900000) // 300000) * 300000
        assert 900000 <= e['decision_ts'] - e['oi_t0'] < 1200000 and e['oi_previous'] == e['oi_t0'] - 3600000
    required = {(s, e[k]) for e in events.values() for s in ('BTCUSDT', 'ETHUSDT') for k in ('oi_t0', 'oi_previous')}
    points = {(p['symbol'], int(p['ts'])): p for p in result['points']}
    assert set(points) == required and len(points) == len(result['points'])
    env = {'__name__': 'ext90_independent_oi', '__file__': str(SOURCE)}
    exec(compile(SOURCE.read_text(encoding='utf-8'), str(SOURCE), 'exec'), env)
    env['runner'] = runner
    archives = [x for x in result['archive_metadata'] if x['status'] == 'verified']
    loaded = {}
    for archive in archives:
        key, values = env['fetch'](archive)
        loaded[key] = values
        print('EXT90_OI_AUDIT_SOURCE', len(loaded), '/', len(archives), key[0], key[1], flush=True)
    for sym in ('BTCUSDT', 'ETHUSDT'):
        p = REF / (sym + '-metrics-5m.parquet')
        assert sha(p) == result['local_metrics_sha256'][sym]
        frame = pq.read_table(p, columns=['ts', 'sum_open_interest']).to_pandas(ignore_metadata=True)
        times = pd.to_datetime(frame.ts, utc=True).astype('datetime64[ns, UTC]').astype('int64') // 1_000_000
        wanted = {t for s, t in required if s == sym}
        frame = frame[np.isin(times.to_numpy(), list(wanted))].copy(); frame['ms'] = times.loc[frame.index]
        local = {}
        for row in frame.itertuples(index=False):
            v = float(row.sum_open_interest)
            local.setdefault(int(row.ms), []).append(str(v) if np.isfinite(v) else None)
        for s, ts in required:
            if s != sym: continue
            point = points[(sym, ts)]
            date = pd.Timestamp(ts, unit='ms', tz='UTC').strftime('%Y-%m-%d')
            official, vals = loaded.get((sym, date), {}).get(ts, []), local.get(ts, [])
            assert point['official_values'] == official and point['local_values'] == vals
            valid = len(official) == len(vals) == 1 and vals[0] is not None and Decimal(official[0]) > 0 and Decimal(official[0]) == Decimal(vals[0])
            assert point['status'] == ('verified' if valid else 'unknown')
    out = {'all_checks_pass': True, 'events_checked': len(events), 'points_checked': len(points),
           'official_archives_redownloaded': len(archives), 'verified_points': sum(p['status'] == 'verified' for p in points.values()),
           'source_sha256': sha(path), 'code_sha256': sha(Path(__file__)), 'source_algorithm_sha256': sha(SOURCE),
           'note': 'Source and causal timestamp audit; historical publication latency is not verified.'}
    (H / '持仓量逐点独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_OI_AUDIT_PASS', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
