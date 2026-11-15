"""Independently audit reused and extended 3R risk paths and source ZIPs."""
import csv
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile

import psutil
import pyarrow.parquet as pq

getcontext().prec = 40
D = Decimal
H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
M = 60000


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def month(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')


def csv_zip(path, key_field, wanted=None):
    rows = {}
    with zipfile.ZipFile(path) as z:
        members = [x for x in z.infolist() if not x.is_dir()]
        assert len(members) == 1 and members[0].filename.endswith('.csv')
        with z.open(members[0]) as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig', newline='')):
                ts = int(row[key_field])
                if wanted is not None and ts not in wanted:
                    continue
                assert ts not in rows
                rows[ts] = row
    return rows


def main(year):
    ledger_path = H / f'{year}三倍止盈风险账本.json'
    data = json.loads(ledger_path.read_text(encoding='utf-8'))
    assert data['year'] == year and data['settlement_code_sha256'] == sha(H / 'settle_3r.py')
    base = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
    manifest_file = base / '完整快照哈希.json'
    assert sha(manifest_file) == data['source_snapshot_sha256']
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    old_file = base / 'batch/动态池单位收益与风险.parquet'
    assert sha(old_file) == manifest['files']['batch/动态池单位收益与风险.parquet']
    old = {(r['observation_id'], r['variant']): r for r in pq.read_table(old_file).to_pylist()}
    records = [r for r in data['records'] if r.get('status') == r.get('risk_status') == 'verified']
    assert len(records) + len([r for r in data['records'] if not (r.get('status') == r.get('risk_status') == 'verified')]) + len(data['replay_unknown']) == data['eligible_2r_paths']
    assert len({(r['observation_id'], r['variant']) for r in records}) == len(records)
    targets = [r for r in records if r['source_mode'] == 'replayed_old_target']
    reused = [r for r in records if r['source_mode'] == 'reuse_non_target']
    assert len(targets) + len(reused) == len(records)
    needed = {}
    for r in targets:
        for ts in range(int(r['entry_ts']) // M * M, int(r['exit_ts']) // M * M + M, M):
            needed.setdefault((r['contract'], month(ts)), set()).add(ts)
    marks, funds, repairs_checked = {}, {}, 0
    for item in data['risk_archives']:
        if item['status'] != 'verified':
            continue
        if shutil.disk_usage(ROOT).free < 2_200_000_000 or psutil.virtual_memory().available < 250 * 1024 ** 2:
            raise RuntimeError('resource_headroom')
        kind, symbol, mon = item['kind'], item['contract'], item['month']
        wants = needed[(symbol, mon)]
        if year == '2023':
            name = f'{symbol}-1m-{mon}.zip' if kind == 'markPriceKlines' else f'{symbol}-fundingRate-{mon}.zip'
            source = ROOT / 'work/breakout_2023_11/raw' / kind / symbol / name
            cache = Path(item['cache_path'])
            assert sha(source) == item['sha256'] and sha(cache) == item['cache_sha256']
            cached = json.loads(cache.read_text(encoding='utf-8'))
            assert cached['status'] == 'verified' and cached['sha256'] == item['sha256']
            assert cached.get('repair') == item.get('repair')
            cache_rows = {int(r['ts']): r for r in cached['rows']}
            assert len(cache_rows) == len(cached['rows'])
            raw = csv_zip(source, 'open_time' if kind == 'markPriceKlines' else 'calc_time', set(cache_rows) if kind == 'markPriceKlines' else None)
            if item.get('repair'):
                fix = item['repair']
                daily = ROOT / 'work/breakout_2023_11/daily_mark_repair' / symbol / f"{symbol}-1m-{fix['day']}.zip"
                assert sha(daily) == fix['sha256']
                extra = csv_zip(daily, 'open_time', set(cache_rows))
                for ts, row in extra.items():
                    if ts in raw:
                        assert all(near(raw[ts][f], row[f]) for f in ('open', 'high', 'low', 'close'))
                    else:
                        raw[ts] = row
                repairs_checked += 1
            assert set(raw) == set(cache_rows)
            fields = ('open', 'high', 'low', 'close') if kind == 'markPriceKlines' else ('funding_interval_hours', 'last_funding_rate')
            for ts, source_row in raw.items():
                assert all(near(source_row[f], cache_rows[ts][f]) for f in fields)
            if kind == 'markPriceKlines':
                for ts, r in cache_rows.items():
                    marks[(symbol, ts)] = {f: D(str(r[f])) for f in ('open', 'high', 'low', 'close')}
            else:
                funds[(symbol, mon)] = {ts: {'interval': D(str(r['funding_interval_hours'])), 'rate': D(str(r['last_funding_rate']))} for ts, r in cache_rows.items()}
        else:
            source = Path(item['path'])
            assert sha(source) == item['sha256']
            raw = csv_zip(source, 'open_time' if kind == 'markPriceKlines' else 'calc_time', wants if kind == 'markPriceKlines' else None)
            if kind == 'markPriceKlines':
                assert set(raw) == wants
                for ts, row in raw.items():
                    marks[(symbol, ts)] = {f: D(row[f]) for f in ('open', 'high', 'low', 'close')}
            else:
                assert raw
                funds[(symbol, mon)] = {ts: {'interval': D(row['funding_interval_hours']), 'rate': D(row['last_funding_rate'])} for ts, row in raw.items()}
    maximum_error = D(0)
    for r in records:
        prior = old[(r['observation_id'], r['variant'].replace('_3r_', '_2r_'))]
        assert prior['status'] == prior['risk_status'] == 'verified' and prior['liq_proxy'] is False
        assert near(prior['net_per_unit_notional'], r['baseline_2r_net']) and r['target_r'] == 3
        for name in ('entry_ts', 'entry_raw', 'entry_fill', 'initial_stop'):
            assert near(prior[name], r[name])
        assert int(r['entry_ts']) >= int(r['entry_signal_reference_ts']) + 1000
        assert int(r['exit_ts']) >= int(r['exit_signal_ts']) + 5000
        if r['source_mode'] == 'reuse_non_target':
            assert prior['reason'] in ('stop', 'quarter_time', 'filled_beyond_risk_budget') and r['reason'] == prior['reason']
            for name in ('exit_signal_ts', 'exit_ts', 'exit_raw', 'exit_fill', 'funding', 'entry_fee', 'exit_fee', 'net_per_unit_notional'):
                assert near(r[name], prior[name])
            assert bool(r['liq_proxy']) == bool(prior['liq_proxy'])
            continue
        assert r['source_mode'] == 'replayed_old_target' and prior['reason'] == 'target'
        assert int(r['exit_signal_ts']) >= int(prior['exit_signal_ts']) and int(r['exit_ts']) >= int(prior['exit_ts'])
        side, lev = int(r['side']), int(r['variant'].rsplit('_', 1)[1].rstrip('x'))
        entry = D(str(r['entry_raw'])) * (1 + D(side) * D('.0005'))
        exit_ = D(str(r['exit_raw'])) * (1 - D(side) * D('.0005'))
        assert near(entry, r['entry_fill']) and near(exit_, r['exit_fill'])
        qty, funding, extrema, events = D(1) / entry, D(0), [], []
        for ts in range(int(r['entry_ts']) // M * M, int(r['exit_ts']) // M * M + M, M):
            mon = month(ts)
            mark, fund = marks[(r['contract'], ts)], funds[(r['contract'], mon)]
            dates = sorted(fund)
            before, after = [t for t in dates if t <= ts], [t for t in dates if t > ts]
            left, right = (before[-1] if before else dates[0]), (after[0] if after else dates[-1])
            allowed = max(fund[left]['interval'], fund[right]['interval']) * D(3600000) * D('1.5')
            gap = right - left if before and after else (ts - left if before else right - ts)
            assert D(gap) <= allowed
            extrema.append(mark['low'] if side == 1 else mark['high'])
            for ft, f in fund.items():
                if ft // M * M != ts or not int(r['entry_ts']) <= ft <= int(r['exit_ts']):
                    continue
                amount = D(side) * qty * mark['open'] * f['rate']
                if ft in (int(r['entry_ts']), int(r['exit_ts'])):
                    amount = max(D(0), amount)
                funding += amount
                events.append(ft)
        exit_fee = qty * exit_ * D('.0005')
        net = D(side) * qty * (exit_ - entry) - D('.0005') - exit_fee - funding
        proxy = any(D(1) / D(lev) - D('.0005') - max(funding, D(0)) + D(side) * qty * (v - entry) <= qty * v * D('.01') for v in extrema)
        assert near(funding, r['funding']) and near(exit_fee, r['exit_fee']) and near(net, r['net_per_unit_notional'])
        assert proxy == r['liq_proxy'] and sorted(events) == sorted(x['settlement_ts'] for x in json.loads(r['funding_events_json']))
        maximum_error = max(maximum_error, abs(net - D(str(r['net_per_unit_notional']))))
    result = {'all_checks_pass': bool(records), 'year': year, 'audited_paths': len(records), 'reused_paths': len(reused),
              'replayed_target_paths': len(targets), 'unknown_replay_paths': len(data['replay_unknown']),
              'unknown_risk_paths': len(data['records']) - len(records), 'liquidation_proxy_paths': sum(bool(r['liq_proxy']) for r in records),
              'daily_repairs_rechecked': repairs_checked, 'max_net_fraction_error': float(maximum_error),
              'ledger_sha256': sha(ledger_path), 'audit_code_sha256': sha(Path(__file__)),
              'note': 'Public ZIP and repaired minute proxies; no actual exchange liquidation or account simulation.'}
    (H / f'{year}三倍止盈账本独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('THREE_R_LEDGER_AUDIT', year, len(records), 'target', len(targets), 'repairs', repairs_checked, flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
