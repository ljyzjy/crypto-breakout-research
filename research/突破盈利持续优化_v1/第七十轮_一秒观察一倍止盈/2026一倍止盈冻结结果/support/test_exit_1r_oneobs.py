"""Test 1R timing, both sides, stop priority and explicit unknowns."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from exit_1r_oneobs import decide


def tape(items):
    return pd.DataFrame({'transact_time': [x[0] for x in items], 'price': [x[1] for x in items]})


def main():
    event = {'side': 1, 'quarter_end': 60000, 'entry_exec_ts': 5000, 'raw_entry_1s': 100.}
    entry = 100.1 * 1.0005
    old = {'status': 'verified', 'entry_ts': 6003, 'entry_raw': 100.1, 'entry_fill': entry, 'initial_stop': 99.65,
           'exit_signal_ts': 25000, 'exit_ts': 30000, 'exit_raw': 101.1, 'reason': 'target'}
    x = tape([(5000, 100.), (6003, 100.1), (15000, 100.7), (20000, 100.6), (25000, 101.2), (30000, 101.1), (65000, 101.)])
    one = decide(event, old, x)
    assert one['status'] == 'verified' and one['reason'] == 'target' and one['exit_signal_ts'] == 15000 and one['exit_ts'] == 20000
    assert abs(one['exit_fill'] - 100.6 * .9995) < 1e-12 and one['target_r'] == 1.
    stop_old = {**old, 'exit_signal_ts': 15000, 'exit_ts': 20000, 'exit_raw': 99.7, 'reason': 'stop'}
    stop = tape([(5000, 100.), (6003, 100.1), (15000, 99.6), (20000, 99.7), (65000, 99.8)])
    assert decide(event, stop_old, stop)['reason'] == 'stop'
    clock_old = {**old, 'exit_signal_ts': 60000, 'exit_ts': 65000, 'exit_raw': 100.2, 'reason': 'quarter_time'}
    clock = tape([(5000, 100.), (6003, 100.1), (20000, 100.2), (60000, 100.2), (65000, 100.2)])
    assert decide(event, clock_old, clock)['reason'] == 'quarter_time'
    invalid = {**old, 'initial_stop': 100.3, 'exit_signal_ts': 6003, 'exit_ts': 15000, 'exit_raw': 100.7, 'reason': 'filled_beyond_risk_budget'}
    assert decide(event, invalid, x)['reason'] == 'filled_beyond_risk_budget'
    tie_old = {**old, 'exit_signal_ts': 15000, 'exit_ts': 20000, 'exit_raw': 100.6, 'reason': 'stop'}
    tie = tape([(5000, 100.), (6003, 100.1), (15000, 100.7), (15000, 99.6), (20000, 100.6), (65000, 100.)])
    assert decide(event, tie_old, tie)['reason'] == 'stop'
    short_event = {**event, 'side': -1}
    short = tape([(5000, 100.), (6003, 99.9), (15000, 99.3), (20000, 99.4), (25000, 98.8), (30000, 98.9)])
    short_old = {**old, 'entry_raw': 99.9, 'entry_fill': 99.9 * .9995, 'initial_stop': 100.35, 'exit_raw': 98.9}
    out = decide(short_event, short_old, short)
    assert out['reason'] == 'target' and out['exit_ts'] == 20000 and abs(out['exit_fill'] - 99.4 * 1.0005) < 1e-12
    assert decide(event, {**old, 'entry_raw': 123.}, x)['status'] == 'entry_disagreement'
    assert decide(event, {**old, 'exit_raw': 123.}, x)['status'] == 'old_exit_disagreement'
    shifted = x.copy()
    shifted.loc[shifted.transact_time.eq(20000), 'price'] = 100.4
    assert decide(event, old, shifted)['exit_signal_ts'] == one['exit_signal_ts']
    here = Path(__file__).resolve().parent
    result = {'all_checks_pass': True, 'one_second_entry_and_five_second_exit': True, 'long_short_tested': True,
              'stop_clock_tie_and_risk_breach_tested': True, 'disagreements_unknown': True,
              'code_sha256': hashlib.sha256((here / 'exit_1r_oneobs.py').read_bytes()).hexdigest()}
    (here / '一秒观察一倍止盈合成核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ONEOBS_1R_SYNTHETIC', json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
