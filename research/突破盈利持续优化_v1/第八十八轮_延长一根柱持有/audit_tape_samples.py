"""Independently replay original and extended tick exits on five fixed-spread samples."""
import hashlib
import json
import math
from pathlib import Path
import sys

import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
R62 = P / '第六十二轮_一秒观察更早突破'
sys.path.insert(0, str(R62))
import audit_tape_samples as original_audit
sys.path.insert(0, str(P / '第四十七轮_一次重新突破确认'))
import public_tape_stream as stream
sys.path.insert(0, str(P / '第三十三轮_动态池逐笔执行'))
import extract_dynamic_tapes as minutes
import run_extension as replay


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def scalar_extended(old, tape, got):
    side, entry, stop = int(old['side']), float(old['entry_fill']), float(old['initial_stop'])
    qend, deadline = int(old['quarter_end']), int(old['quarter_end']) + 900000
    target = entry + side * 2 * side * (entry - stop)
    sequence = list(zip(tape.transact_time.astype('int64'), tape.price.astype(float)))
    outcome, i = (deadline, 'extended_quarter_time'), 0
    while i < len(sequence):
        t = int(sequence[i][0]); j = i + 1
        while j < len(sequence) and sequence[j][0] == t:
            j += 1
        if qend < t <= deadline:
            values = [p for _, p in sequence[i:j]]
            if any(side * (p - stop) <= 0 for p in values):
                outcome = t, 'stop'; break
            if any(side * (p - target) >= 0 for p in values):
                outcome = t, 'target'; break
        if t > deadline:
            break
        i = j
    exit_ = next((x for x in sequence if x[0] >= outcome[0] + 5000), None)
    assert exit_ is not None and got['status'] == 'verified'
    assert int(got['exit_signal_ts']) == outcome[0] and got['reason'] == outcome[1]
    assert int(got['exit_ts']) == int(exit_[0]) and near(got['exit_raw'], exit_[1])
    assert near(got['exit_fill'], exit_[1] * (1 - side * .0005))
    assert int(got['entry_ts']) == int(old['entry_ts']) and near(got['entry_fill'], old['entry_fill'])


def main():
    replay.guardlib.guard(start=True)
    test = json.loads((R62 / '独立重放合成核验.json').read_text(encoding='utf-8'))
    assert test['all_checks_pass'] and test['audit_code_sha256'] == sha(R62 / 'audit_tape_samples.py')
    sources = json.loads((H / '原柱末退出回放输入.json').read_text(encoding='utf-8'))
    progress = json.loads((H / '延长持有逐笔进度.json').read_text(encoding='utf-8'))
    assert progress['fingerprint'] == replay.fingerprint()
    available = []
    grouped = {}
    for item in sources['events']:
        event = item['event']
        grouped.setdefault((item['period'], event['contract'], event['day']), []).append(item)
    for (period, sym, day), events in grouped.items():
        path = replay.WORK / (replay.key_for(progress['fingerprint'], period, sym, day, events) + '.json')
        if not path.exists():
            continue
        cp = json.loads(path.read_text(encoding='utf-8'))
        assert cp['fingerprint'] == progress['fingerprint'] and cp['status'] == 'verified'
        rows = {x['observation_id']: x for x in cp['rows']}
        for item in events:
            r = rows[item['event']['observation_id']]
            if r['status'] == 'verified':
                available.append((item, cp, r))
    available.sort(key=lambda x: (x[0]['period'], x[0]['event']['observation_id']))
    assert len(available) >= 5
    indexes = sorted({i * (len(available) - 1) // 4 for i in range(5)})
    assert len(indexes) == 5
    samples = []
    for i in indexes:
        item, cp, row = available[i]
        event = item['event']; obs = event['observation_id']
        body, bar_meta = minutes.archive('klines', event['contract'], event['day'])
        bars = minutes.minute_bars(body, event['day']); del body
        expected_bar = next(a for a in cp['archives'] if a['kind'] == 'klines')
        assert bar_meta['sha256'] == expected_bar['sha256']
        blocks, archives = [], []
        for prev in (a for a in cp['archives'] if a['kind'] == 'aggTrades'):
            windows = {obs: (int(event['trigger_minute']), int(event['quarter_end']) + 900000 + 60000)}
            got, meta = stream.fetch(event['contract'], prev['day'], windows, replay.guardlib.guard)
            assert meta['sha256'] == prev['sha256'] and meta['bytes'] == prev['bytes']
            blocks.extend(got[obs]); archives.append(meta)
        assert blocks
        tape = pd.concat(blocks, ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
        checked_original = original_audit.replay(event, tape, bars, item['checkpoint']['row'])
        assert checked_original == 2
        for old in item['paths']:
            scalar_extended(old, tape, row['paths'][old['variant']])
        samples.append({'period': item['period'], 'observation_id': obs, 'original_paths_checked': checked_original,
                        'extended_paths_checked': 2, 'minute_sha256': bar_meta['sha256'], 'tape_archives': archives})
        print('EXT88_TAPE_SAMPLE', len(samples), '/5', flush=True)
    out = {'all_checks_pass': True, 'samples': samples, 'paths_checked': sum(x['extended_paths_checked'] for x in samples),
           'replay_fingerprint': progress['fingerprint'], 'code_sha256': sha(Path(__file__)),
           'note': 'Five scalar replay samples; source is same-exchange history, not actual fills.'}
    (H / '延长持有逐笔独立核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT88_TAPE_AUDIT', len(samples), out['paths_checked'], flush=True)


if __name__ == '__main__':
    main()
