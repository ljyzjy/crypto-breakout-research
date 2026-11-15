"""Independent scalar replay of selected 1R source-tape paths."""
import json
import math
from pathlib import Path
import sys
import time

import pandas as pd
import psutil
import replay_1r as replay

H, ROOT = replay.H, replay.ROOT


def near(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-11)


def check(event, old, actual, tape):
    seq = list(zip(tape.transact_time.astype('int64'), tape.price.astype(float)))
    assert seq and all(seq[i][0] <= seq[i + 1][0] for i in range(len(seq) - 1))
    ref = next((x for x in seq if x[0] >= event['entry_exec_ts']), None)
    assert ref and ref[0] == event['entry_exec_ts'] and near(ref[1], event['raw_entry_1s'])
    entry = next((x for x in seq if x[0] >= ref[0] + 1000), None)
    assert entry and entry[0] == old['entry_ts'] == actual['entry_ts'] and near(entry[1], old['entry_raw'])
    side = int(event['side'])
    fill = entry[1] * (1 + side * .0005)
    assert near(fill, actual['entry_fill']) and near(fill, old['entry_fill'])
    stop = float(old['initial_stop'])
    if old['reason'] == 'filled_beyond_risk_budget':
        signal, reason = entry[0], 'filled_beyond_risk_budget'
    else:
        dist = side * (fill - stop)
        assert dist > 0
        target = fill + side * dist
        signal, reason = event['quarter_end'], 'quarter_time'
        i = 0
        while i < len(seq):
            ts = seq[i][0]
            j = i + 1
            while j < len(seq) and seq[j][0] == ts:
                j += 1
            if entry[0] <= ts <= event['quarter_end']:
                prices = [p for _, p in seq[i:j]]
                if any(side * (p - stop) <= 0 for p in prices):
                    signal, reason = ts, 'stop'
                    break
                if any(side * (p - target) >= 0 for p in prices):
                    signal, reason = ts, 'target'
                    break
            if ts > event['quarter_end']:
                break
            i = j
    exit_ = next((x for x in seq if x[0] >= signal + 5000), None)
    assert exit_ and signal == actual['exit_signal_ts'] and reason == actual['reason']
    assert exit_[0] == actual['exit_ts'] and near(exit_[1], actual['exit_raw'])
    assert near(actual['exit_fill'], exit_[1] * (1 - side * .0005))
    assert signal <= old['exit_signal_ts'] and exit_[0] <= old['exit_ts']


def main(year):
    tasks, fp, eligible, source_sha = replay.prepare(year)
    folder = ROOT / 'work' / f'oneobs1r70_{year}' / 'tape'
    available = []
    for spec in tasks:
        path = folder / (replay.key(fp, spec['checkpoint']) + '.json')
        if not path.exists():
            continue
        cp = json.loads(path.read_text(encoding='utf-8'))
        assert cp['fingerprint'] == fp and cp['source_checkpoint'] == spec['checkpoint']
        rows = {r['observation_id']: r for r in cp['rows']}
        for event in spec['events']:
            row = rows.get(event['observation_id'], {})
            for variant, old in sorted(event['old_paths'].items()):
                alt = row.get('paths', {}).get(variant.replace('_2r_', '_1r_'))
                if alt and alt.get('status') == 'verified':
                    available.append((spec, event, variant, old, alt))
    chosen, groups = [], set()
    for field in ('target', 'stop', 'quarter_time', 'filled_beyond_risk_budget'):
        sample = next((x for x in available if x[4]['reason'] == field and x[0]['checkpoint'] not in groups), None)
        if sample:
            chosen.append(sample)
            groups.add(sample[0]['checkpoint'])
    for side in (1, -1):
        sample = next((x for x in available if x[1]['side'] == side and x[0]['checkpoint'] not in groups), None)
        if sample and len(chosen) < 5:
            chosen.append(sample)
            groups.add(sample[0]['checkpoint'])
    for sample in available:
        if len(chosen) >= 3:
            break
        if sample[0]['checkpoint'] not in groups:
            chosen.append(sample)
            groups.add(sample[0]['checkpoint'])
    assert len(chosen) >= 3
    results = []
    for spec, event, variant, old, actual in chosen:
        while psutil.virtual_memory().available < 500 * 1024 ** 2:
            replay.guard()
            time.sleep(3)
        blocks = []
        obs = event['observation_id']
        for expected in spec['archives']:
            got, meta = replay.public.fetch(spec['contract'], expected['day'],
                                             {obs: (event['trigger_minute'], event['quarter_end'] + 60000)}, replay.guard)
            assert meta['sha256'] == expected['sha256'] and meta['bytes'] == expected['bytes']
            blocks.extend(got[obs])
        assert blocks
        tape = pd.concat(blocks, ignore_index=True).sort_values(['transact_time', 'agg_trade_id'], kind='mergesort')
        check(event, old, actual, tape)
        results.append({'observation_id': obs, 'variant': variant, 'reason': actual['reason'], 'side': event['side']})
        print('ONEOBS_1R_TAPE_SAMPLE', year, len(results), '/', len(chosen), flush=True)
    result = {'all_checks_pass': True, 'year': year, 'samples': results, 'eligible_paths': eligible,
              'replay_fingerprint': fp, 'source_snapshot_sha256': source_sha, 'audit_code_sha256': replay.sha(Path(__file__)),
              'note': 'Independent scalar checks use public market prints, not actual order fills.'}
    (H / f'{year}一倍止盈逐笔独立核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_1R_TAPE_PASS', year, len(results), flush=True)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('2024', '2026')
    main(sys.argv[1])
