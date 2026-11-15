"""Verify mark and funding sources and settle all replayed extended paths."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
R81 = P / '第八十一轮_八至十月一秒观察'
sys.path.insert(0, str(P / '第三十三轮_动态池逐笔执行'))
import settle_dynamic_paths as risk
import run_extension as replay

WORK = ROOT / 'work' / 'oneobs88_extend' / 'risk'
M = 60000


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def month(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime('%Y-%m')


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def main():
    replay.guardlib.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert sha(Path(risk.__file__)) == frozen['sources_sha256']['risk_engine']
    progress = json.loads((H / '延长持有逐笔进度.json').read_text(encoding='utf-8'))
    assert progress['fingerprint'] == replay.fingerprint() and progress['frozen_sha256'] == sha(H / '冻结时点.json')
    initial = json.loads((H / '原柱末退出回放输入.json').read_text(encoding='utf-8'))
    grouped = {}
    for e in initial['events']:
        grouped.setdefault((e['period'], e['event']['contract'], e['event']['day']), []).append(e)
    fp = progress['fingerprint']
    paired, unknown, required = [], [], {}
    for (period, symbol, day), events in grouped.items():
        path = replay.WORK / (replay.key_for(fp, period, symbol, day, events) + '.json')
        saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if saved:
            assert saved['status'] == 'verified' and saved['fingerprint'] == fp
            rows = {r['observation_id']: r for r in saved['rows']}
        else:
            rows = {}
        for e in events:
            obs = e['event']['observation_id']
            row = rows.get(obs, {})
            for old in e['paths']:
                alt = row.get('paths', {}).get(old['variant'])
                if not alt or alt['status'] != 'verified':
                    unknown.append({'period': period, 'observation_id': obs, 'variant': old['variant'], 'status': (alt or {}).get('status', row.get('status', 'replay_unknown'))})
                    continue
                assert int(alt['entry_ts']) == int(old['entry_ts']) and near(alt['entry_fill'], old['entry_fill'])
                assert int(alt['exit_signal_ts']) >= int(old['exit_signal_ts']) and int(alt['exit_ts']) >= int(old['exit_ts'])
                for ts in range(int(old['entry_ts']) // M * M, int(alt['exit_ts']) // M * M + M, M):
                    required.setdefault((period, symbol, month(ts)), set()).add(ts)
                paired.append((period, symbol, e['event'], old, alt))
    assert len(paired) + len(unknown) == 68
    expected = {}
    old_freeze = json.loads((P / '第七十九轮_完成周线趋势/冻结时点.json').read_text(encoding='utf-8'))
    for period in ('2023', '2024', '2026', '2026_aug_oct'):
        if period == '2026_aug_oct':
            root = R81 / '冻结结果'; manifest = root / '冻结哈希.json'; name = 'batch/风险来源与结算.json'
            assert sha(manifest) == frozen['sources_sha256']['r81_snapshot']
        else:
            root = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if period == '2023' else f'第六十二轮_一秒观察更早突破/{period}完整批次_冻结')
            manifest = root / '完整快照哈希.json'; name = 'batch/动态池风险档案核验清单.json'
            assert sha(manifest) == old_freeze['base_snapshots'][period]
        m = json.loads(manifest.read_text(encoding='utf-8'))
        assert sha(root / name) == m['files'][name]
        z = json.loads((root / name).read_text(encoding='utf-8'))
        rows = z['sources'] if isinstance(z, dict) else z
        for rec in rows:
            expected[(period, rec['kind'], rec['contract'], rec['month'])] = rec
    specs = []
    for (period, symbol, mon), times in sorted(required.items()):
        for kind in ('markPriceKlines', 'fundingRate'):
            specs.append((period, kind, symbol, mon, sorted(times) if kind == 'markPriceKlines' else []))
    risk.WORK = WORK; WORK.mkdir(parents=True, exist_ok=True)
    risk.FINGERPRINT = hashlib.sha256((sha(H / '冻结时点.json') + fp + sha(Path(__file__)) + sha(Path(risk.__file__))).encode()).hexdigest()
    def fetch(spec):
        replay.guardlib.guard()
        period, kind, symbol, mon, times = spec
        rec = risk.task((kind, symbol, mon, times))
        prior = expected.get((period, kind, symbol, mon))
        if rec.get('status') == 'verified' and prior and prior.get('status') == 'verified' and rec.get('sha256') != prior.get('sha256'):
            return period, {**rec, 'status': 'original_source_sha_changed', 'rows': []}, times
        return period, rec, times
    responses = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(fetch, spec) for spec in specs]
        for i, job in enumerate(as_completed(jobs), 1):
            responses.append(job.result())
            if i % 10 == 0 or i == len(jobs):
                print('EXT88_RISK_SOURCE', i, '/', len(jobs), 'unknown', sum(x[1]['status'] != 'verified' for x in responses), flush=True)
    marks, funds, status, archives = {}, {}, {}, []
    for period, rec, times in responses:
        kind, symbol, mon = rec['kind'], rec['contract'], rec['month']
        status[(period, kind, symbol, mon)] = rec['status']
        if rec['status'] == 'verified':
            if kind == 'markPriceKlines':
                for row in rec['rows']: marks[(period, symbol, int(row['ts']))] = row
            else:
                funds[(period, symbol, mon)] = rec['rows']
        cache_key = hashlib.sha256((risk.FINGERPRINT + '|' + kind + '|' + symbol + '|' + mon + '|' + ','.join(map(str, times))).encode()).hexdigest()
        cache = WORK / (cache_key + '.json')
        meta = {k: v for k, v in rec.items() if k != 'rows'}
        meta.update({'period': period, 'cache_path': str(cache) if cache.exists() else None, 'cache_sha256': sha(cache) if cache.exists() else None})
        archives.append(meta)
    records = []
    for period, symbol, event, old, alt in paired:
        original_months = {month(ts) for ts in range(int(old['entry_ts']) // M * M, int(alt['exit_ts']) // M * M + M, M)}
        local_status = {(k, symbol, mon): status.get((period, k, symbol, mon), 'missing') for k in ('markPriceKlines', 'fundingRate') for mon in original_months}
        local_marks = {(symbol, ts): value for (per, s, ts), value in marks.items() if per == period and s == symbol}
        local_funds = {(symbol, mon): value for (per, s, mon), value in funds.items() if per == period and s == symbol}
        kwargs = {'contract': symbol, 'side': int(old['side']), 'variant': old['variant']}
        old_input = {k: v for k, v in old.items() if k not in kwargs}
        new_input = {k: v for k, v in alt.items() if k not in kwargs}
        before = risk.settle(SimpleNamespace(**kwargs, **old_input), local_marks, local_funds, local_status)
        after = risk.settle(SimpleNamespace(**kwargs, **new_input), local_marks, local_funds, local_status)
        if before['risk_status'] != 'verified' or after['risk_status'] != 'verified':
            unknown.append({'period': period, 'observation_id': event['observation_id'], 'variant': old['variant'],
                            'status': 'risk_unknown', 'old_risk': before['risk_status'], 'new_risk': after['risk_status']})
            continue
        if not all(near(before[k], old[k]) for k in ('funding', 'net_per_unit_notional')) or bool(before['liq_proxy']) != bool(old['liq_proxy']):
            unknown.append({'period': period, 'observation_id': event['observation_id'], 'variant': old['variant'], 'status': 'original_risk_replay_disagreement'})
            continue
        if after['liq_proxy']:
            unknown.append({'period': period, 'observation_id': event['observation_id'], 'variant': old['variant'], 'status': 'extended_liquidation_proxy'})
            continue
        records.append({'period': period, 'observation_id': event['observation_id'], 'variant': old['variant'],
                        'contract': symbol, 'side': int(old['side']), 'decision_ts': int(old['decision_ts']),
                        'quarter_end': int(old['quarter_end']), 'original': old, 'extended': alt, 'risk': after})
    assert len(records) + len(unknown) == 68
    out = {'records': records, 'unknown': unknown, 'risk_archives': archives, 'required_archive_count': len(specs),
           'replay_fingerprint': fp, 'inputs_sha256': sha(H / '原柱末退出回放输入.json'),
           'progress_sha256': sha(H / '延长持有逐笔进度.json'), 'risk_engine_sha256': sha(Path(risk.__file__)),
           'code_sha256': sha(Path(__file__)),
           'note': 'Old and new risk checked; proxy liquidation and any mismatch remain unknown.'}
    (H / '延长持有风险账本.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('EXT88_SETTLED', 'verified_paths', len(records), 'unknown_paths', len(unknown), 'risk_archives', len(specs), flush=True)


if __name__ == '__main__':
    main()
