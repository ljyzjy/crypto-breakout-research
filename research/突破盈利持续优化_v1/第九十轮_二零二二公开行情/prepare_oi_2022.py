"""Match decision-time BTC/ETH open-interest points to official verified archives."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import replay_2022 as runner

H = Path(__file__).resolve().parent
P = H.parent
REF = Path(r'C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\metrics')
SOURCE = P / '第八十二轮_八至十月持仓量过滤/prepare_oi.py'


def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def load_archive():
    env = {'__name__': 'ext90_oi_source', '__file__': str(SOURCE)}
    exec(compile(SOURCE.read_text(encoding='utf-8'), str(SOURCE), 'exec'), env)
    env['runner'] = runner
    return env


def day(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m-%d')


def main():
    runner.guard(start=True)
    risk = json.loads((H / '风险来源与账本独立核验.json').read_text(encoding='utf-8'))
    ledger_path = H / '一秒回放批次/动态池单位收益与风险.parquet'
    assert risk['all_checks_pass'] and risk['ledger_sha256'] == sha(ledger_path)
    assert risk['code_sha256'] == sha(H / 'audit_risk_2022.py')
    ledger = pq.read_table(ledger_path).to_pylist()
    events = {}
    for r in ledger:
        if r['status'] != 'verified' or r['risk_status'] != 'verified' or r['liq_proxy'] is not False:
            continue
        obs, decision = r['observation_id'], int(r['decision_ts'])
        now = ((decision - 900000) // 300000) * 300000
        assert 900000 <= decision - now < 1200000
        event = {'observation_id': obs, 'decision_ts': decision, 'oi_t0': now, 'oi_previous': now - 3600000}
        if obs in events: assert events[obs] == event
        events[obs] = event
    required = {(sym, e[k]) for e in events.values() for sym in ('BTCUSDT', 'ETHUSDT') for k in ('oi_t0', 'oi_previous')}
    local, local_hashes = {}, {}
    for sym in ('BTCUSDT', 'ETHUSDT'):
        path = REF / (sym + '-metrics-5m.parquet')
        local_hashes[sym] = sha(path)
        needed = np.array(sorted(t for s, t in required if s == sym), dtype=np.int64)
        table = pq.ParquetFile(path)
        for batch in table.iter_batches(columns=['sum_open_interest', 'ts'], batch_size=8192, use_threads=False):
            runner.guard()
            times = batch.column(1).cast(pa.int64()).to_numpy(zero_copy_only=False) // 1000
            values = batch.column(0).to_numpy(zero_copy_only=False)
            for i in np.flatnonzero(np.isin(times, needed)):
                v = float(values[i])
                local.setdefault((sym, int(times[i])), []).append(str(v) if math.isfinite(v) else None)
    archive = load_archive()['archive']
    specs = sorted({(sym, day(ts)) for sym, ts in required})
    downloaded = {}
    for spec in specs:
        runner.guard()
        rec = archive(spec); downloaded[spec] = rec
        print('EXT90_OI_SOURCE', len(downloaded), '/', len(specs), spec[0], spec[1], rec['status'], flush=True)
    points = []
    for sym, ts in sorted(required):
        item = downloaded[(sym, day(ts))]
        raw, loc = item['values'].get(ts, []), local.get((sym, ts), [])
        good = (item['status'] == 'verified' and len(raw) == len(loc) == 1 and loc[0] is not None
                and Decimal(raw[0]).is_finite() and Decimal(raw[0]) > 0 and Decimal(raw[0]) == Decimal(loc[0]))
        points.append({'symbol': sym, 'ts': ts, 'official_values': raw, 'local_values': loc,
                       'status': 'verified' if good else 'unknown', 'archive_sha256': item.get('sha256')})
    metadata = [{k: v for k, v in rec.items() if k != 'values'} for rec in downloaded.values()]
    out = {'events': list(events.values()), 'points': points, 'archive_metadata': metadata,
           'point_counts': {'required': len(points), 'verified': sum(x['status'] == 'verified' for x in points)},
           'frozen_sha256': sha(H / '冻结时点.json'), 'code_sha256': sha(Path(__file__)),
           'risk_audit_sha256': sha(H / '风险来源与账本独立核验.json'), 'local_metrics_sha256': local_hashes,
           'source_algorithm_sha256': sha(SOURCE),
           'note': 'Official/local agreement; historical publication delay is not established.'}
    (H / '持仓量逐点来源核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT90_OI_PREPARED', len(events), out['point_counts'], flush=True)


if __name__ == '__main__':
    main()
