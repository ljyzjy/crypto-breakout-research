"""Synthetic 3R versus 2R exit, tie, delay and unchanged-path checks."""
import hashlib
import json
from pathlib import Path

import pandas as pd
from exit_3r import decide

H = Path(__file__).resolve().parent


def tape(items):
    return pd.DataFrame({'transact_time': [x[0] for x in items], 'price': [x[1] for x in items]})


def main():
    event = {'side': 1, 'quarter_end': 60000, 'entry_exec_ts': 5000, 'raw_entry_1s': 100.}
    entry = 100.1 * 1.0005
    old = {'status': 'verified', 'entry_ts': 6003, 'entry_raw': 100.1, 'entry_fill': entry,
           'entry_signal_reference_ts': 5000, 'initial_stop': 99.65, 'actual_entry_risk': entry - 99.65,
           'exit_signal_ts': 15000, 'exit_ts': 20000, 'exit_raw': 101.8, 'exit_fill': 101.8 * .9995,
           'reason': 'target', 'fast_fail': False}
    x = tape([(5000, 100.), (6003, 100.1), (15000, 101.2), (19000, 101.8), (20000, 101.8), (25000, 101.5), (65000, 101.)])
    a = decide(event, old, x)
    assert a['status'] == 'verified' and a['reason'] == 'target' and a['exit_signal_ts'] == 19000 and a['exit_ts'] == 25000
    assert a['target_r'] == 3. and abs(a['exit_fill'] - 101.5 * .9995) < 1e-12
    y = tape([(5000, 100.), (6003, 100.1), (15000, 101.2), (20000, 101.8), (21000, 99.5), (26000, 99.4), (65000, 100.)])
    b = decide(event, old, y)
    assert b['status'] == 'verified' and b['reason'] == 'target' and b['exit_signal_ts'] == 20000
    z = tape([(5000, 100.), (6003, 100.1), (15000, 101.2), (20000, 101.4), (21000, 99.5), (26000, 99.4), (65000, 100.)])
    retrace_old = {**old, 'exit_raw': 101.4, 'exit_fill': 101.4 * .9995}
    c = decide(event, retrace_old, z)
    assert c['status'] == 'verified' and c['reason'] == 'stop' and c['exit_signal_ts'] == 21000 and c['exit_ts'] == 26000
    clock = tape([(5000, 100.), (6003, 100.1), (15000, 101.2), (20000, 101.4), (60000, 101.3), (65000, 101.2)])
    d = decide(event, retrace_old, clock)
    assert d['reason'] == 'quarter_time' and d['exit_signal_ts'] == 60000 and d['exit_ts'] == 65000
    tie = tape([(5000, 100.), (6003, 100.1), (15000, 101.2), (20000, 101.4), (21000, 101.8), (21000, 99.5), (26000, 99.6)])
    assert decide(event, retrace_old, tie)['reason'] == 'stop'
    stop_old = {**old, 'reason': 'stop', 'exit_signal_ts': 10000, 'exit_ts': 15000, 'exit_raw': 99.5, 'exit_fill': 99.5 * .9995}
    reused = decide(event, stop_old)
    assert reused['source_mode'] == 'reuse_non_target' and reused['reason'] == 'stop' and reused['exit_ts'] == stop_old['exit_ts']
    invalid = {**stop_old, 'reason': 'filled_beyond_risk_budget'}
    assert decide(event, invalid)['reason'] == 'filled_beyond_risk_budget'
    assert decide(event, {**old, 'exit_signal_ts': 15001}, x)['status'] == 'old_trigger_disagreement'
    short_event = {**event, 'side': -1}
    short = tape([(5000, 100.), (6003, 99.9), (15000, 98.8), (19000, 98.2), (20000, 98.2), (25000, 98.5)])
    short_entry = 99.9 * .9995
    short_old = {**old, 'entry_raw': 99.9, 'entry_fill': short_entry, 'initial_stop': 100.35,
                 'actual_entry_risk': 100.35 - short_entry, 'exit_raw': 98.2, 'exit_fill': 98.2 * 1.0005}
    short_result = decide(short_event, short_old, short)
    assert short_result['reason'] == 'target' and short_result['exit_signal_ts'] == 19000 and near(short_result['exit_fill'], 98.5 * 1.0005)
    result = {'all_checks_pass': True, 'code_sha256': hashlib.sha256((H / 'exit_3r.py').read_bytes()).hexdigest(),
              'plan_sha256': hashlib.sha256((H / '冻结研究方案.md').read_bytes()).hexdigest(),
              'test_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'checks': ['target_2r_then_3r', 'stop_after_2r', 'quarter_end', 'same_ms_stop_priority', 'non_target_reuse', 'short', 'source_mismatch']}
    (H / '三倍止盈合成核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('THREE_R_SYNTHETIC_PASS', json.dumps(result, ensure_ascii=False), flush=True)


def near(a, b):
    return abs(a - b) < 1e-11


if __name__ == '__main__':
    main()
