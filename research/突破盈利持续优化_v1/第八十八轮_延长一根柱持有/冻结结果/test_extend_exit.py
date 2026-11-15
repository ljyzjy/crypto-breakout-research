import hashlib
import json
from pathlib import Path

from extend_exit import EXTRA, extend_path

H = Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def case(side=1):
    entry, stop = (100, 99) if side == 1 else (100, 101)
    return {'side': side, 'entry_fill': entry, 'initial_stop': stop, 'quarter_end': 10000,
            'entry_ts': 2000, 'entry_raw': entry, 'entry_signal_reference_ts': 1000,
            'exit_ts': 15000, 'exit_raw': 100.1, 'reason': 'quarter_time'}


def main():
    long = case()
    tape = [(2000, 100), (9999, 100.2), (15000, 100.1), (20000, 102), (25000, 102.1), (10000 + EXTRA + 5000, 102.2)]
    a = extend_path(long, tape)
    assert a['status'] == 'verified' and a['reason'] == 'target' and a['exit_signal_ts'] == 20000 and a['exit_ts'] == 25000
    assert extend_path(long, tape + [(10000 + EXTRA + 10000, 1)]) == a
    stop_tie = [(2000, 100), (15000, 100.1), (20000, 102), (20000, 99), (25000, 98.9)]
    b = extend_path(long, stop_tie)
    assert b['reason'] == 'stop' and b['exit_signal_ts'] == 20000
    short_tape = [(2000, 100), (15000, 100.1), (20000, 98), (25000, 97.9)]
    assert extend_path(case(-1), short_tape)['reason'] == 'target'
    time_tape = [(2000, 100), (15000, 100.1), (10000 + EXTRA, 100), (10000 + EXTRA + 5000, 100.2)]
    c = extend_path(long, time_tape)
    assert c['reason'] == 'extended_quarter_time' and c['exit_ts'] == 10000 + EXTRA + 5000
    assert extend_path(long, [(2000, 100), (9999, 99), (15000, 100.1)])['status'] == 'unknown_old_trigger_disagreement'
    assert extend_path(long, [(2000, 100), (15000, 100.3)])['status'] == 'unknown_old_exit_disagreement'
    assert extend_path(long, [(2000, 100), (15000, 100.1)])['status'] == 'unknown_missing_extended_exit'
    out = {'all_checks_pass': True, 'checks': ['long_short', 'old_exit_reproduced', 'same_ms_stop_priority',
           'next_quarter_time', 'minimum_exit_delay', 'unknown_missing_data', 'future_perturbation'],
           'engine_sha256': sha(H / 'extend_exit.py'), 'test_code_sha256': sha(Path(__file__))}
    (H / '延长持有合成核验.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('EXT88_TEST', json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
