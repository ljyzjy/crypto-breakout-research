"""Replay fixed 1R exits only for independently verified 2R entries.

All archive hashes and outputs remain separate from the original research run.
The source ZIP is streamed and verified in full; no partial archive is trusted.
"""
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import pandas as pd
import psutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
PRIOR = P / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(P / '第四十七轮_一次重新突破确认'))
import public_tape_stream as public
sys.path.insert(0, str(P / '第四十八轮_固定一倍风险止盈'))
import public_range
import exit_1r_oneobs


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available < 250 * 1024 ** 2:
        raise RuntimeError('memory_headroom')


def key(fingerprint, checkpoint):
    return hashlib.sha256((fingerprint + '|' + checkpoint).encode()).hexdigest()


def prepare(year):
    snap = PRIOR / f'{year}完整批次_冻结'
    manifest_path = snap / '完整快照哈希.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['all_checks_pass'] and manifest['year'] == year
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md') and not frozen['2024_batch_settlement_exists']
    test = json.loads((H / '一秒观察一倍止盈合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['code_sha256'] == sha(H / 'exit_1r_oneobs.py')
    stream_audit_path = P / '第四十七轮_一次重新突破确认/无落盘逐笔读取真实样本核验.json'
    stream_audit = json.loads(stream_audit_path.read_text(encoding='utf-8'))
    assert stream_audit['all_checks_pass'] and stream_audit['stream_code_sha256'] == sha(Path(public.__file__))
    range_audit = json.loads((P / '第四十八轮_固定一倍风险止盈/分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert range_audit['all_checks_pass'] and range_audit['range_code_sha256'] == sha(Path(public_range.__file__))
    assert range_audit['stream_code_sha256'] == sha(Path(public.__file__))
    audit = json.loads((snap / f'support/{year}一秒观察账本独立核验.json').read_text(encoding='utf-8'))
    assert audit['all_checks_pass']
    names = ['batch/动态池逐笔信号筛查.parquet', 'batch/动态池延迟市价路径.parquet',
             'batch/动态池单位收益与风险.parquet', f'support/{year}一秒观察账本独立核验.json']
    for name in names:
        assert sha(snap / name) == manifest['files'][name]
    signal = pd.read_parquet(snap / names[0]).set_index('observation_id')
    paths = pd.read_parquet(snap / names[1]).set_index(['observation_id', 'variant'])
    ledger = pd.read_parquet(snap / names[2])
    verified = ledger[(ledger.status == 'verified') & (ledger.risk_status == 'verified') & ledger.liq_proxy.eq(False)]
    assert len(verified) and not verified.duplicated(['observation_id', 'variant']).any()
    chosen = {(r['observation_id'], r['variant']): r for r in verified.to_dict('records')}
    tasks, used = [], set()
    for name, digest in sorted(manifest['files'].items()):
        if not name.startswith('checkpoints/'):
            continue
        path = snap / name
        assert sha(path) == digest
        cp = json.loads(path.read_text(encoding='utf-8'))
        assert cp['status'] == 'verified'
        events = []
        for row in cp['rows']:
            obs = row['observation_id']
            old_paths = {}
            for lev in (10, 20):
                variant = f'one_observation_2r_{lev}x'
                if (obs, variant) not in chosen:
                    continue
                assert obs in signal.index and (obs, variant) in paths.index
                old = paths.loc[(obs, variant)].to_dict()
                cp_old = row['paths'][variant]
                for field in ('status', 'entry_ts', 'entry_raw', 'entry_fill', 'exit_signal_ts', 'exit_ts', 'exit_raw', 'initial_stop', 'reason'):
                    assert cp_old[field] == old[field], (obs, field)
                old_paths[variant] = old
                assert (obs, variant) not in used
                used.add((obs, variant))
            if old_paths:
                s = signal.loc[obs]
                events.append({'observation_id': obs, 'trigger_minute': int(s.trigger_minute),
                               'quarter_end': int(s.quarter_end), 'decision_ts': int(s.decision_ts),
                               'entry_exec_ts': int(s.entry_exec_ts),
                               'raw_entry_1s': float(s.raw_entry_1s), 'side': int(s.side), 'old_paths': old_paths})
        if events:
            archives = [x for x in cp['archives'] if x['kind'] == 'aggTrades']
            assert archives and len({a['day'] for a in archives}) == len(archives)
            tasks.append({'checkpoint': name, 'contract': cp['contract'], 'day': cp['day'], 'archives': archives, 'events': events})
    assert used == set(chosen)
    tasks.sort(key=lambda z: (sum(int(a['bytes']) for a in z['archives']), z['day'], z['contract']))
    code_paths = [Path(__file__), H / 'exit_1r_oneobs.py', H / 'test_exit_1r_oneobs.py', H / '冻结研究方案.md',
                  H / '冻结时点.json', Path(public.__file__), Path(public_range.__file__), manifest_path]
    fingerprint = hashlib.sha256(''.join(sha(p) for p in code_paths).encode()).hexdigest()
    return tasks, fingerprint, len(chosen), sha(manifest_path)


def task(spec, fingerprint, folder):
    dest = folder / (key(fingerprint, spec['checkpoint']) + '.json')
    if dest.exists():
        saved = json.loads(dest.read_text(encoding='utf-8'))
        assert saved['fingerprint'] == fingerprint and saved['source_checkpoint'] == spec['checkpoint']
        return saved
    error = ''
    for attempt in range(3):
        try:
            while psutil.virtual_memory().available < 500 * 1024 ** 2:
                guard()
                time.sleep(3)
            guard()
            blocks = {e['observation_id']: [] for e in spec['events']}
            archives = []
            windows = {e['observation_id']: (e['trigger_minute'], e['quarter_end'] + 60000) for e in spec['events']}
            public_range.WORKERS = 2
            for expected in spec['archives']:
                public_range.MAX_BUFFER = 50_000_000 if psutil.virtual_memory().available >= 1536 * 1024 ** 2 else 0
                out, meta = public_range.fetch(spec['contract'], expected['day'], windows, guard)
                if meta['sha256'] != expected['sha256'] or meta['bytes'] != expected['bytes']:
                    raise ValueError('original_archive_changed')
                archives.append(meta)
                for obs in blocks:
                    blocks[obs].extend(out[obs])
            rows = []
            for event in spec['events']:
                obs = event['observation_id']
                if not blocks[obs]:
                    rows.append({'observation_id': obs, 'status': 'missing_event_tape'})
                    continue
                tape = pd.concat(blocks[obs], ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
                paths = {}
                for variant, old in event['old_paths'].items():
                    paths[variant.replace('_2r_', '_1r_')] = exit_1r_oneobs.decide(event, old, tape)
                rows.append({'observation_id': obs, 'status': 'processed', 'paths': paths})
            result = {'fingerprint': fingerprint, 'source_checkpoint': spec['checkpoint'], 'contract': spec['contract'],
                      'day': spec['day'], 'status': 'verified', 'archives': archives, 'rows': rows}
            guard()
            tmp = dest.with_suffix('.partial')
            tmp.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            tmp.replace(dest)
            return result
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)[:160]
            if 'headroom' in error or 'stream_cap' in error or 'window_exceeds' in error:
                break
            if attempt < 2:
                time.sleep(attempt + 1)
    return {'status': 'error', 'error': error, 'contract': spec['contract'], 'day': spec['day']}


def main(year):
    tasks, fp, paths, snapshot_sha = prepare(year)
    folder = ROOT / 'work' / f'oneobs1r70_{year}' / 'tape'
    folder.mkdir(parents=True, exist_ok=True)
    print('ONEOBS_1R_TASKS', year, len(tasks), 'risk_verified_paths', paths, flush=True)
    attempted, errors = 0, []
    for spec in tasks:
        try:
            guard()
        except RuntimeError as exc:
            errors.append({'status': 'guard_stop', 'error': str(exc)})
            break
        result = task(spec, fp, folder)
        if result['status'] != 'verified':
            errors.append({k: result.get(k) for k in ('contract', 'day', 'error')})
            if 'headroom' in result['error']:
                break
        attempted += 1
        if attempted % 5 == 0:
            print('ONEOBS_1R_PROGRESS', year, attempted, '/', len(tasks), 'errors', len(errors), flush=True)
    summary = {'year': year, 'attempted_groups': attempted, 'total_groups': len(tasks), 'verified_2r_paths': paths,
               'errors': errors, 'fingerprint': fp, 'source_snapshot_sha256': snapshot_sha,
               'note': 'Checkpoint errors and missing/invalid 1R paths are unknown; no account simulation.'}
    (H / f'{year}一倍止盈逐笔进度.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_1R_STOP', json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2024', '2026')
    main(sys.argv[1])
