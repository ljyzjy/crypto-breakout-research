"""Re-read only verified 2R-target events; other paths provably stay unchanged."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import pandas as pd
import psutil

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
sys.path.insert(0, str(P / '第四十七轮_一次重新突破确认'))
import public_tape_stream as public
sys.path.insert(0, str(P / '第四十八轮_固定一倍风险止盈'))
import public_range
import exit_3r


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def guard():
    if shutil.disk_usage(ROOT).free < 2_200_000_000:
        raise RuntimeError('disk_headroom')
    if psutil.virtual_memory().available < 250 * 1024 ** 2:
        raise RuntimeError('memory_headroom')


def key(fp, checkpoint):
    return hashlib.sha256((fp + '|' + checkpoint).encode()).hexdigest()


def prepare(year):
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    test = json.loads((H / '三倍止盈合成核验.json').read_text(encoding='utf-8'))
    assert sha(H / '冻结研究方案.md') == frozen['plan_sha256'] == test['plan_sha256']
    assert test['all_checks_pass'] and test['code_sha256'] == sha(H / 'exit_3r.py') and test['test_code_sha256'] == sha(H / 'test_exit_3r.py')
    real = json.loads((P / '第四十八轮_固定一倍风险止盈/分段逐笔读取核验.json').read_text(encoding='utf-8'))
    assert real['all_checks_pass'] and real['range_code_sha256'] == sha(Path(public_range.__file__)) and real['stream_code_sha256'] == sha(Path(public.__file__))
    base = P / ('第七十三轮_二零二三扩展核验/2023基础冻结结果' if year == '2023' else f'第六十二轮_一秒观察更早突破/{year}完整批次_冻结')
    manifest_path = base / '完整快照哈希.json'
    assert sha(manifest_path) == frozen['base_snapshots'][year]
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['all_checks_pass']
    names = ['batch/动态池逐笔信号筛查.parquet', 'batch/动态池延迟市价路径.parquet', 'batch/动态池单位收益与风险.parquet']
    for name in names:
        assert sha(base / name) == manifest['files'][name]
    signals = pd.read_parquet(base / names[0]).set_index('observation_id')
    paths = pd.read_parquet(base / names[1]).set_index(['observation_id', 'variant'])
    ledger = pd.read_parquet(base / names[2])
    ledger = ledger[(ledger.status == 'verified') & (ledger.risk_status == 'verified') & ledger.liq_proxy.eq(False)]
    chosen = {(r['observation_id'], r['variant']): r for r in ledger.to_dict('records')}
    assert len(chosen) and not ledger.duplicated(['observation_id', 'variant']).any()
    tasks, used, reusable = [], set(), []
    for name, digest in sorted(manifest['files'].items()):
        if not name.startswith('checkpoints/'):
            continue
        path = base / name
        assert sha(path) == digest
        cp = json.loads(path.read_text(encoding='utf-8'))
        assert cp['status'] == 'verified'
        events = []
        for row in cp['rows']:
            obs = row['observation_id']
            targets = {}
            for lev in (10, 20):
                variant = f'one_observation_2r_{lev}x'
                if (obs, variant) not in chosen:
                    continue
                old = paths.loc[(obs, variant)].to_dict()
                cp_old = row['paths'][variant]
                for field in ('status', 'entry_ts', 'entry_raw', 'entry_fill', 'exit_signal_ts', 'exit_ts', 'exit_raw', 'initial_stop', 'reason'):
                    assert old[field] == cp_old[field]
                assert (obs, variant) not in used
                used.add((obs, variant))
                s = signals.loc[obs]
                event = {'observation_id': obs, 'trigger_minute': int(s.trigger_minute), 'quarter_end': int(s.quarter_end),
                         'decision_ts': int(s.decision_ts), 'entry_exec_ts': int(s.entry_exec_ts),
                         'raw_entry_1s': float(s.raw_entry_1s), 'side': int(s.side)}
                if old['reason'] == 'target':
                    targets[variant] = old
                else:
                    new = exit_3r.decide(event, old)
                    assert new['status'] == 'verified' and new['source_mode'] == 'reuse_non_target'
                    reusable.append({'observation_id': obs, 'variant': variant.replace('_2r_', '_3r_'), 'contract': cp['contract'],
                                     'event': event, 'old': old, 'path': new})
            if targets:
                events.append({**event, 'old_paths': targets})
        if events:
            archives = [x for x in cp['archives'] if x['kind'] == 'aggTrades']
            assert archives and len({a['day'] for a in archives}) == len(archives)
            tasks.append({'checkpoint': name, 'contract': cp['contract'], 'day': cp['day'], 'archives': archives, 'events': events})
    assert used == set(chosen)
    tasks.sort(key=lambda z: (sum(int(x['bytes']) for x in z['archives']), z['day'], z['contract']))
    paths_for_fp = [Path(__file__), H / 'exit_3r.py', H / 'test_exit_3r.py', H / '冻结研究方案.md', H / '冻结时点.json',
                    Path(public.__file__), Path(public_range.__file__), manifest_path]
    fp = hashlib.sha256(''.join(sha(p) for p in paths_for_fp).encode()).hexdigest()
    return tasks, reusable, fp, len(chosen), sha(manifest_path)


def task(spec, fp, folder):
    dest = folder / (key(fp, spec['checkpoint']) + '.json')
    if dest.exists():
        old = json.loads(dest.read_text(encoding='utf-8'))
        assert old['fingerprint'] == fp and old['source_checkpoint'] == spec['checkpoint']
        return old
    error = ''
    for attempt in range(3):
        try:
            while psutil.virtual_memory().available < 500 * 1024 ** 2:
                guard()
                time.sleep(3)
            guard()
            blocks = {e['observation_id']: [] for e in spec['events']}
            windows = {e['observation_id']: (e['trigger_minute'], e['quarter_end'] + 60000) for e in spec['events']}
            archives = []
            public_range.WORKERS = 2
            for expected in spec['archives']:
                public_range.MAX_BUFFER = 50_000_000 if psutil.virtual_memory().available >= 1536 * 1024 ** 2 else 0
                got, meta = public_range.fetch(spec['contract'], expected['day'], windows, guard)
                assert meta['sha256'] == expected['sha256'] and meta['bytes'] == expected['bytes']
                archives.append(meta)
                for obs in blocks:
                    blocks[obs].extend(got[obs])
            rows = []
            for event in spec['events']:
                obs = event['observation_id']
                if not blocks[obs]:
                    rows.append({'observation_id': obs, 'status': 'missing_event_tape'})
                    continue
                tape = pd.concat(blocks[obs], ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
                result = {variant.replace('_2r_', '_3r_'): exit_3r.decide(event, old, tape) for variant, old in event['old_paths'].items()}
                rows.append({'observation_id': obs, 'status': 'processed', 'paths': result})
            out = {'fingerprint': fp, 'source_checkpoint': spec['checkpoint'], 'contract': spec['contract'],
                   'day': spec['day'], 'status': 'verified', 'archives': archives, 'rows': rows}
            guard()
            temp = dest.with_suffix('.partial')
            temp.write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            temp.replace(dest)
            return out
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)[:160]
            if 'headroom' in error or 'stream_cap' in error or 'window_exceeds' in error:
                break
            if attempt < 2:
                time.sleep(attempt + 1)
    return {'status': 'error', 'error': error, 'contract': spec['contract'], 'day': spec['day']}


def main(year):
    tasks, reusable, fp, eligible, source_sha = prepare(year)
    folder = ROOT / 'work' / f'oneobs3r78_{year}' / 'tape'
    folder.mkdir(parents=True, exist_ok=True)
    print('THREE_R_TASKS', year, len(tasks), 'reuse_paths', len(reusable), 'eligible_paths', eligible, flush=True)
    done, errors = 0, []
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
        done += 1
        if done % 5 == 0:
            print('THREE_R_PROGRESS', year, done, '/', len(tasks), 'errors', len(errors), flush=True)
    result = {'year': year, 'attempted_groups': done, 'total_groups': len(tasks), 'reused_paths': len(reusable),
              'eligible_paths': eligible, 'errors': errors, 'fingerprint': fp, 'source_snapshot_sha256': source_sha}
    (H / f'{year}三倍止盈逐笔进度.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('THREE_R_STOP', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2023', '2024', '2026')
    main(sys.argv[1])
