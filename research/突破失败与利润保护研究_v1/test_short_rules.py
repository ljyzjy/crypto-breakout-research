"""Mirror the timing/gap tests for short positions."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('exit_long_test', HERE / 'verify_exit_engine.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
M, base = m.M, m.base
m.default = np.array([100.4, 100.8, 100.0, 100.4, 100., 1e6])
m.row = {**m.row, 'side': -1, 'signal_close': 100.4, 'stop_price': 102., 'level': 100.5}
m.frame = pd.DataFrame([m.row])

lock_bars = {base+4*M: [100.4,100.8,98.5,98.6,100.,1e6],
             base+9*M: [100.4,100.8,98.5,98.6,100.,1e6],
             base+10*M: [100.4,100.8,100.,100.4,100.,1e6]}
result, trade = m.run(lock_bars, lock_profit=True)
scheduled = [e for e in result['rule_events'] if e['kind'] == 'lock_scheduled']
applied = [e for e in result['rule_events'] if e['kind'] == 'lock_applied']
assert len(scheduled) == len(applied) == 1
assert scheduled[0]['known_ts'] == base+10*M and scheduled[0]['effective_ts'] == base+11*M
assert trade['exit_ts'] == base+11*M and trade['reason'] == 'gap_stop' and trade['net'] < 0

failure_bars = {base+14*M: [100.4,100.8,100.,100.6,100.,1e6]}
result, trade = m.run(failure_bars, failure_exit=True)
events = [e for e in result['rule_events'] if e['kind'] == 'failure_scheduled']
assert len(events) == 1 and events[0]['known_ts'] == base+15*M and events[0]['effective_ts'] == base+16*M
assert trade['exit_ts'] == base+16*M and trade['reason'] == 'failed_breakout'

report = {'short_complete_five_minute_required': True, 'short_lock_one_minute_delay': True,
          'short_gap_can_lose': True, 'short_failed_breakout_exit_one_minute_delay': True}
(HERE / '做空退出规则合成核验.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('SHORT_EXIT_SYNTHETICS_PASS', json.dumps(report), flush=True)
