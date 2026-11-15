"""Recheck fixed-entry 1R paths against SHA-verified local mark/funding ZIPs."""
import csv
from datetime import datetime, timezone
import importlib.util
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pandas as pd
import replay_1r as replay

H, P, ROOT = replay.H, replay.P, replay.ROOT
M = 60000


def month(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def source_path(year, kind, symbol, mon):
    if kind == 'markPriceKlines':
        name = f'{symbol}-1m-{mon}.zip'
        base = Path(r'D:\CodexResearch_2024_mark_571e490ad9c146329044a750196f552f') if year == '2024' else ROOT / 'work/breakout_forward_2026/markPriceKlines'
    else:
        name = f'{symbol}-fundingRate-{mon}.zip'
        base = ROOT / ('work/breakout_2024_11/raw/fundingRate' if year == '2024' else 'work/breakout_forward_2026/fundingRate')
    return base / symbol / name


def load_risk(year, needed, expected):
    marks, funds, statuses, archives = {}, {}, {}, []
    for (symbol, mon), minutes in sorted(needed.items()):
        for kind in ('markPriceKlines', 'fundingRate'):
            replay.guard()
            key = (kind, symbol, mon)
            item = expected.get(key)
            path = source_path(year, kind, symbol, mon)
            detail = {'kind': kind, 'contract': symbol, 'month': mon, 'path': str(path)}
            try:
                assert item and item['status'] == 'verified' and path.is_file(), 'verified_local_source_missing'
                digest = replay.sha(path)
                assert digest == item['sha256'], 'source_sha_mismatch'
                rows = {}
                with zipfile.ZipFile(path) as archive:
                    members = [x for x in archive.infolist() if not x.is_dir()]
                    assert len(members) == 1 and members[0].filename.endswith('.csv')
                    with archive.open(members[0]) as binary:
                        for row in csv.DictReader(io.TextIOWrapper(binary, encoding='utf-8-sig', newline='')):
                            ts = int(row['open_time' if kind == 'markPriceKlines' else 'calc_time'])
                            if kind == 'markPriceKlines' and ts not in minutes:
                                continue
                            assert ts not in rows and month(ts) == mon
                            if kind == 'markPriceKlines':
                                values = {f: float(row[f]) for f in ('open', 'high', 'low', 'close')}
                                assert ts % M == 0 and all(math.isfinite(v) and v > 0 for v in values.values())
                                assert values['low'] <= min(values['open'], values['close'], values['high'])
                                assert values['high'] >= max(values['open'], values['close'], values['low'])
                                rows[ts] = {'ts': ts, **values}
                            else:
                                interval, rate = float(row['funding_interval_hours']), float(row['last_funding_rate'])
                                assert math.isfinite(interval) and interval > 0 and math.isfinite(rate)
                                rows[ts] = {'ts': ts, 'funding_interval_hours': interval, 'last_funding_rate': rate}
                if kind == 'markPriceKlines':
                    assert set(rows) == minutes, 'mark_minutes_missing'
                    for ts, value in rows.items():
                        marks[(symbol, ts)] = value
                else:
                    assert rows, 'funding_rows_missing'
                    funds[(symbol, mon)] = [rows[t] for t in sorted(rows)]
                statuses[key] = 'verified'
                detail.update({'status': 'verified', 'sha256': digest, 'rows_used': len(rows)})
            except Exception as exc:
                statuses[key] = 'unavailable_or_invalid'
                detail.update({'status': 'unavailable_or_invalid', 'error': type(exc).__name__ + ':' + str(exc)[:120]})
            archives.append(detail)
    return marks, funds, statuses, archives


def main(year):
    tasks, fp, eligible_paths, snapshot_sha = replay.prepare(year)
    snapshot = P / f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结'
    manifest = json.loads((snapshot / '完整快照哈希.json').read_text(encoding='utf-8'))
    risk_name = 'batch/动态池风险档案核验清单.json'
    assert replay.sha(snapshot / risk_name) == manifest['files'][risk_name]
    risk_manifest = json.loads((snapshot / risk_name).read_text(encoding='utf-8'))
    expected = {(x['kind'], x['contract'], x['month']): x for x in risk_manifest}
    assert len(expected) == len(risk_manifest)
    ledger = pd.read_parquet(snapshot / 'batch/动态池单位收益与风险.parquet')
    old_ledger = {(r['observation_id'], r['variant']): r for r in ledger.to_dict('records')}
    directory = ROOT / 'work' / f'oneobs1r70_{year}' / 'tape'
    needed, pairs, missing = {}, [], []
    for task in tasks:
        path = directory / (replay.key(fp, task['checkpoint']) + '.json')
        saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if saved:
            assert saved['fingerprint'] == fp and saved['source_checkpoint'] == task['checkpoint'] and saved['status'] == 'verified'
            rows = {r['observation_id']: r for r in saved['rows']}
        else:
            rows = {}
        for event in task['events']:
            obs = event['observation_id']
            for variant, old in event['old_paths'].items():
                alt = rows.get(obs, {}).get('paths', {}).get(variant.replace('_2r_', '_1r_'))
                if not alt or alt.get('status') != 'verified':
                    missing.append({'observation_id': obs, 'variant': variant, 'status': (alt or {}).get('status', 'replay_unknown')})
                    continue
                assert alt['entry_ts'] == old['entry_ts'] and near(alt['entry_fill'], old['entry_fill'])
                assert int(alt['exit_ts']) <= int(old['exit_ts']) and int(alt['exit_signal_ts']) <= int(old['exit_signal_ts'])
                for ts in range(int(old['entry_ts']) // M * M, int(old['exit_ts']) // M * M + M, M):
                    needed.setdefault((task['contract'], month(ts)), set()).add(ts)
                pairs.append((task['contract'], event, variant, old, alt))
    assert len(pairs) + len(missing) == eligible_paths
    marks, funds, statuses, archives = load_risk(year, needed, expected)
    engine_path = P / '第四十四轮_双币过滤跨时段复核/settle_cross_engine.py'
    spec = importlib.util.spec_from_file_location('oneobs1r_risk', engine_path)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    records = []
    for contract, event, variant, old, alt in pairs:
        common = {'contract': contract, 'side': event['side']}
        before = engine.settle(SimpleNamespace(**common, **old, variant=variant), marks, funds, statuses)
        prior = old_ledger[(event['observation_id'], variant)]
        if before['risk_status'] != 'verified':
            records.append({'observation_id': event['observation_id'], 'variant': variant.replace('_2r_', '_1r_'), 'status': 'risk_source_unknown', 'old_risk_status': before['risk_status']})
            continue
        for field in ('funding', 'entry_fee', 'exit_fee', 'net_per_unit_notional'):
            assert near(before[field], prior[field]), (event['observation_id'], variant, field)
        assert bool(before['liq_proxy']) == bool(prior['liq_proxy'])
        new_variant = variant.replace('_2r_', '_1r_')
        after = engine.settle(SimpleNamespace(**common, **alt, variant=new_variant), marks, funds, statuses)
        records.append({'observation_id': event['observation_id'], 'variant': new_variant, 'contract': contract,
                        'side': event['side'], 'decision_ts': event['decision_ts'], 'quarter_end': event['quarter_end'],
                        **alt, **after, 'baseline_2r_net': float(prior['net_per_unit_notional'])})
    result = {'year': year, 'source_snapshot_sha256': snapshot_sha, 'replay_fingerprint': fp,
              'eligible_2r_paths': eligible_paths, 'replayed_pairs': len(pairs), 'replay_unknown': missing,
              'risk_archives': archives, 'records': records,
              'source_engine_sha256': replay.sha(engine_path), 'settlement_code_sha256': replay.sha(Path(__file__)),
              'note': 'Local ZIP hashes were compared with previously checked official source hashes; missing sources remain unknown.'}
    out = H / f'{year}一倍止盈本地风险账本.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('ONEOBS_1R_RISK', year, 'paths', len(records), 'replay_unknown', len(missing),
          'source_unknown', sum(x['status'] != 'verified' for x in archives), flush=True)


if __name__ == '__main__':
    import sys
    assert len(sys.argv) == 2 and sys.argv[1] in ('2024', '2026')
    main(sys.argv[1])
