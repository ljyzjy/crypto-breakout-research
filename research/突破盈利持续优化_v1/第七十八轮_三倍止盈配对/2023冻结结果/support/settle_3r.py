"""Reprice 3R target paths with audited local mark and funding sources."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

import pandas as pd
import psutil
import replay_3r_targets as replay

H, P, ROOT = replay.H, replay.P, replay.ROOT
M = 60000
sys.path.insert(0, str(P / '第七十轮_一秒观察一倍止盈'))
import settle_1r_local as local_later


def month(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def risk_2023(needed, expected, source_sha):
    old = P / '第四十三轮_旧十一币2023年复核'
    sys.path.insert(0, str(old))
    import settle_local_2023_serial as local
    frozen = json.loads((old / '风险来源冻结哈希.json').read_text(encoding='utf-8'))
    assert replay.sha(old / '冻结研究方案.md') == frozen['plan_sha256']
    assert json.loads((old / '本地风险来源串行合成核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    local.engine.FINGERPRINT = hashlib.sha256((replay.sha(H / '冻结研究方案.md') + source_sha + replay.sha(Path(__file__))).encode()).hexdigest()
    marks, funds, statuses, archives = {}, {}, {}, []
    for (symbol, mon), times in sorted(needed.items()):
        for kind in ('markPriceKlines', 'fundingRate'):
            while psutil.virtual_memory().available < 850 * 1024 ** 2:
                replay.guard()
                time.sleep(3)
            replay.guard()
            values = sorted(times) if kind == 'markPriceKlines' else []
            rec = local.local_task((kind, symbol, mon, values))
            replay.guard()
            key = (kind, symbol, mon)
            prior = expected.get(key)
            if rec.get('status') == 'verified' and prior and prior.get('status') == 'verified' and rec.get('sha256') == prior.get('sha256'):
                statuses[key] = 'verified'
                cache_key = hashlib.sha256((local.engine.FINGERPRINT + '|' + local.EXTRA + '|' + kind + '|' + symbol + '|' + mon + '|' + ','.join(map(str, values))).encode()).hexdigest()
                cache = local.WORK / (cache_key + '.json')
                assert cache.is_file()
                if kind == 'markPriceKlines':
                    for r in rec['rows']:
                        marks[(symbol, int(r['ts']))] = r
                else:
                    funds[(symbol, mon)] = rec['rows']
                archives.append({k: rec.get(k) for k in ('kind', 'contract', 'month', 'status', 'sha256', 'repair')} |
                                {'cache_path': str(cache), 'cache_sha256': replay.sha(cache), 'rows_used': len(rec['rows'])})
            else:
                statuses[key] = 'unavailable_or_invalid'
                archives.append({'kind': kind, 'contract': symbol, 'month': mon, 'status': 'unavailable_or_invalid',
                                 'error': rec.get('error', 'source_missing_or_changed')})
    return marks, funds, statuses, archives, local.engine


def main(year):
    tasks, reusable, fp, eligible, source_sha = replay.prepare(year)
    progress = json.loads((H / f'{year}三倍止盈逐笔进度.json').read_text(encoding='utf-8'))
    assert progress['fingerprint'] == fp and progress['attempted_groups'] == progress['total_groups'] == len(tasks) and not progress['errors']
    snap = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
    manifest = json.loads((snap / '完整快照哈希.json').read_text(encoding='utf-8'))
    risk_file = snap / 'batch/动态池风险档案核验清单.json'
    assert replay.sha(risk_file) == manifest['files']['batch/动态池风险档案核验清单.json']
    risks = json.loads(risk_file.read_text(encoding='utf-8'))
    expected = {(x['kind'], x['contract'], x['month']): x for x in risks}
    assert len(expected) == len(risks)
    ledger = pd.read_parquet(snap / 'batch/动态池单位收益与风险.parquet')
    ledger_map = {(x['observation_id'], x['variant']): x for x in ledger.to_dict('records')}
    folder = ROOT / 'work' / f'oneobs3r78_{year}' / 'tape'
    target_pairs, missing, needed = [], [], {}
    for task in tasks:
        path = folder / (replay.key(fp, task['checkpoint']) + '.json')
        saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if saved:
            assert saved['fingerprint'] == fp and saved['source_checkpoint'] == task['checkpoint'] and saved['status'] == 'verified'
            rows = {r['observation_id']: r for r in saved['rows']}
        else:
            rows = {}
        for event in task['events']:
            obs = event['observation_id']
            for variant, old in event['old_paths'].items():
                alt = rows.get(obs, {}).get('paths', {}).get(variant.replace('_2r_', '_3r_'))
                if not alt or alt.get('status') != 'verified':
                    missing.append({'observation_id': obs, 'variant': variant, 'status': (alt or {}).get('status', 'replay_unknown')})
                    continue
                assert alt['entry_ts'] == old['entry_ts'] and near(alt['entry_fill'], old['entry_fill'])
                assert int(alt['exit_signal_ts']) >= int(old['exit_signal_ts']) and int(alt['exit_ts']) >= int(old['exit_ts'])
                for ts in range(int(old['entry_ts']) // M * M, int(alt['exit_ts']) // M * M + M, M):
                    needed.setdefault((task['contract'], month(ts)), set()).add(ts)
                target_pairs.append((task['contract'], event, variant, old, alt))
    assert len(reusable) + len(target_pairs) + len(missing) == eligible
    if year == '2023':
        marks, funds, statuses, archives, engine = risk_2023(needed, expected, source_sha)
    else:
        marks, funds, statuses, archives = local_later.load_risk(year, needed, expected)
        engine_path = P / '第四十四轮_双币过滤跨时段复核/settle_cross_engine.py'
        spec = importlib.util.spec_from_file_location('three_r_risk', engine_path)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
    records = []
    for item in reusable:
        variant_old = item['variant'].replace('_3r_', '_2r_')
        old = ledger_map[(item['observation_id'], variant_old)]
        assert old['status'] == old['risk_status'] == 'verified' and old['liq_proxy'] is False
        alt, e = item['path'], item['event']
        assert all(near(alt[k], old[k]) for k in ('entry_ts', 'entry_raw', 'entry_fill', 'exit_signal_ts', 'exit_ts', 'exit_raw', 'exit_fill'))
        records.append({'observation_id': item['observation_id'], 'variant': item['variant'], 'contract': item['contract'],
                        'side': e['side'], 'decision_ts': e['decision_ts'], 'quarter_end': e['quarter_end'], **alt,
                        **{k: old[k] for k in ('risk_status', 'funding', 'funding_events_json', 'liq_proxy', 'entry_fee', 'exit_fee', 'net_per_unit_notional')},
                        'baseline_2r_net': float(old['net_per_unit_notional'])})
    for contract, event, variant, old, alt in target_pairs:
        common = {'contract': contract, 'side': event['side']}
        old_result = engine.settle(SimpleNamespace(**common, **old, variant=variant), marks, funds, statuses)
        prior = ledger_map[(event['observation_id'], variant)]
        if old_result['risk_status'] != 'verified':
            records.append({'observation_id': event['observation_id'], 'variant': variant.replace('_2r_', '_3r_'),
                            'status': 'risk_source_unknown', 'old_risk_status': old_result['risk_status']})
            continue
        for field in ('funding', 'entry_fee', 'exit_fee', 'net_per_unit_notional'):
            assert near(old_result[field], prior[field]), (event['observation_id'], variant, field)
        assert bool(old_result['liq_proxy']) == bool(prior['liq_proxy'])
        new_variant = variant.replace('_2r_', '_3r_')
        new_risk = engine.settle(SimpleNamespace(**common, **alt, variant=new_variant), marks, funds, statuses)
        records.append({'observation_id': event['observation_id'], 'variant': new_variant, 'contract': contract,
                        'side': event['side'], 'decision_ts': event['decision_ts'], 'quarter_end': event['quarter_end'],
                        **alt, **new_risk, 'baseline_2r_net': float(prior['net_per_unit_notional'])})
    result = {'year': year, 'source_snapshot_sha256': source_sha, 'replay_fingerprint': fp, 'eligible_2r_paths': eligible,
              'reused_paths': len(reusable), 'replayed_target_paths': len(target_pairs), 'replay_unknown': missing,
              'risk_archives': archives, 'records': records, 'settlement_code_sha256': replay.sha(Path(__file__)),
              'note': 'Unchanged non-target 2R paths are reused; extended target paths have mark/funding rechecked.'}
    (H / f'{year}三倍止盈风险账本.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('THREE_R_RISK', year, 'records', len(records), 'replay_unknown', len(missing),
          'source_unknown', sum(x['status'] != 'verified' for x in archives), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
