"""Stream SHA-verified public tapes and replay all original quarter-time exits."""
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import pandas as pd

from extend_exit import extend_path

H = Path(__file__).resolve().parent
P = H.parent
ROOT = P.parent.parent
R81 = P / '第八十一轮_八至十月一秒观察'
R62 = P / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(R81))
import run_replay as guardlib
sys.path.insert(0, str(R62))
import one_second_observation as engine
sys.path.insert(0, str(P / '第三十三轮_动态池逐笔执行'))
import extract_dynamic_tapes as minutes
sys.path.insert(0, str(P / '第四十八轮_固定一倍风险止盈'))
import public_range

WORK = ROOT / 'work' / 'oneobs88_extend' / 'tape'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-8)


def fingerprint():
    paths = [H / '冻结时点.json', H / '原柱末退出回放输入.json', Path(__file__), H / 'extend_exit.py',
             H / '延长持有合成核验.json', R62 / 'one_second_observation.py',
             P / '第三十三轮_动态池逐笔执行/extract_dynamic_tapes.py', P / '第三十三轮_动态池逐笔执行/leveraged_paths.py',
             P / '第四十八轮_固定一倍风险止盈/public_range.py', P / '第四十七轮_一次重新突破确认/public_tape_stream.py']
    return hashlib.sha256(''.join(sha(p) for p in paths).encode()).hexdigest()


def key_for(fp, period, symbol, date, events):
    value = '|'.join([fp, period, symbol, date, *sorted(x['event']['observation_id'] for x in events)])
    return hashlib.sha256(value.encode()).hexdigest()


def original_matches(result, item):
    stored = item['checkpoint']['row']
    if result['status'] != stored['status'] or result['status'] != 'qualified':
        return False
    for name in ('side', 'decision_ts', 'entry_exec_ts', 'one_count'):
        if int(result[name]) != int(stored[name]):
            return False
    for name in ('signal_close', 'raw_entry_1s', 'buy_notional', 'sell_notional', 'one_imbalance', 'stop_price', 'level'):
        if not near(result[name], stored[name]):
            return False
    if result['prechecks'] != stored['prechecks']:
        return False
    for original in item['paths']:
        candidate = result['paths'].get(original['variant'])
        if not candidate or candidate['status'] != 'verified' or original['reason'] != 'quarter_time':
            return False
        for name in ('entry_ts', 'exit_signal_ts', 'exit_ts'):
            if int(candidate[name]) != int(original[name]):
                return False
        for name in ('entry_raw', 'entry_fill', 'exit_raw', 'exit_fill', 'initial_stop'):
            if not near(candidate[name], original[name]):
                return False
        if candidate['reason'] != original['reason']:
            return False
    return True


def task(fp, period, symbol, date, events):
    dest = WORK / (key_for(fp, period, symbol, date, events) + '.json')
    if dest.exists():
        z = json.loads(dest.read_text(encoding='utf-8'))
        assert z['status'] == 'verified' and z['fingerprint'] == fp
        return z
    for x in events:
        assert sha(Path(x['checkpoint']['path'])) == x['checkpoint']['sha256']
    error = ''
    for attempt in range(3):
        try:
            guardlib.guard()
            body, bar = minutes.archive('klines', symbol, date)
            bars = minutes.minute_bars(body, date); del body
            for x in events:
                expected_bar = next(a for a in x['checkpoint']['archives'] if a['kind'] == 'klines' and a['day'] == date)
                assert bar['sha256'] == expected_bar['sha256'] and bar['bytes'] == expected_bar['bytes']
            end = max(int(x['event']['quarter_end']) + 900000 + 60000 for x in events)
            dates = pd.date_range(pd.Timestamp(date, tz='UTC'), pd.Timestamp(end - 1, unit='ms', tz='UTC').normalize(), freq='D').strftime('%Y-%m-%d').tolist()
            blocks = {x['event']['observation_id']: [] for x in events}
            archives = [bar]
            for day in dates:
                windows = {x['event']['observation_id']: (int(x['event']['trigger_minute']), int(x['event']['quarter_end']) + 900000 + 60000) for x in events}
                data, meta = public_range.fetch(symbol, day, windows, guardlib.guard)
                archives.append(meta)
                for x in events:
                    old = [a for a in x['checkpoint']['archives'] if a['kind'] == 'aggTrades' and a['day'] == day]
                    if old:
                        assert len(old) == 1 and old[0]['sha256'] == meta['sha256'] and old[0]['bytes'] == meta['bytes']
                    blocks[x['event']['observation_id']].extend(data[x['event']['observation_id']])
            rows = []
            for item in events:
                event, obs = item['event'], item['event']['observation_id']
                if not blocks[obs]:
                    rows.append({'observation_id': obs, 'status': 'unknown_missing_tape', 'paths': {}})
                    continue
                tape = pd.concat(blocks[obs], ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
                original = engine.decide(event, tape, bars)
                if not original_matches(original, item):
                    rows.append({'observation_id': obs, 'status': 'unknown_original_replay_disagreement', 'paths': {}})
                    continue
                prices = list(zip(tape.transact_time.astype('int64'), tape.price.astype(float)))
                paths = {r['variant']: extend_path(r, prices) for r in item['paths']}
                rows.append({'observation_id': obs, 'status': 'verified' if all(x['status'] == 'verified' for x in paths.values()) else 'unknown_extended_path',
                             'paths': paths})
            out = {'status': 'verified', 'fingerprint': fp, 'period': period, 'symbol': symbol, 'day': date,
                   'archives': archives, 'rows': rows}
            guardlib.guard()
            temp = dest.with_suffix('.partial'); temp.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8'); temp.replace(dest)
            return out
        except Exception as exc:
            error = type(exc).__name__ + ':' + str(exc)[:180]
            if any(x in error for x in ('headroom', 'stream_cap', 'window_exceeds', '404', 'AssertionError')):
                break
            if attempt < 2:
                print('EXT88_RETRY', symbol, date, attempt + 1, type(exc).__name__, flush=True)
                time.sleep(attempt + 1)
    return {'status': 'error', 'period': period, 'symbol': symbol, 'day': date, 'error': error}


def main():
    guardlib.guard(start=True)
    frozen = json.loads((H / '冻结时点.json').read_text(encoding='utf-8'))
    assert frozen['plan_sha256'] == sha(H / '冻结研究方案.md')
    for k, p in frozen['source_paths'].items():
        assert sha(Path(p)) == frozen['sources_sha256'][k]
    sources = json.loads((H / '原柱末退出回放输入.json').read_text(encoding='utf-8'))
    assert sources['frozen_sha256'] == sha(H / '冻结时点.json') and sources['code_sha256'] == sha(H / 'build_replay_inputs.py')
    WORK.mkdir(parents=True, exist_ok=True)
    grouped = {}
    for x in sources['events']:
        e = x['event']
        grouped.setdefault((x['period'], e['contract'], e['day']), []).append(x)
    groups = [(p, s, day, xs) for (p, s, day), xs in grouped.items()]
    groups.sort(key=lambda z: (sum(a.get('bytes', 0) for a in z[3][0]['checkpoint']['archives'] if a['kind'] == 'aggTrades'), z[1], z[2]))
    fp, done, errors = fingerprint(), 0, []
    print('EXT88_START', len(groups), 'groups', len(sources['events']), 'events', flush=True)
    for period, sym, day, events in groups:
        try:
            guardlib.guard()
            z = task(fp, period, sym, day, events)
        except Exception as exc:
            z = {'status': 'error', 'period': period, 'symbol': sym, 'day': day, 'error': type(exc).__name__ + ':' + str(exc)[:180]}
        if z['status'] == 'verified':
            done += 1
        else:
            errors.append(z)
        print('EXT88_GROUP', done, '/', len(groups), 'errors', len(errors), period, sym, day, z['status'], flush=True)
        if z['status'] != 'verified' and 'headroom' in z['error']:
            break
    progress = {'total_events': len(sources['events']), 'total_groups': len(groups), 'completed_groups': done,
                'errors': errors, 'fingerprint': fp, 'frozen_sha256': sha(H / '冻结时点.json'),
                'note': 'Replay checkpoints only; risk and independent audit remain outstanding.'}
    (H / '延长持有逐笔进度.json').write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT88_STOP', json.dumps(progress, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
