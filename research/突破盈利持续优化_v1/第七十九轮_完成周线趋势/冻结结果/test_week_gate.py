"""Run synthetic boundary, missing-source, strict-equality and future-leak tests."""
import hashlib
import json
from pathlib import Path

from week_gate import W, MON, gate, last_completed_week

H = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    monday = MON + 3000 * W
    assert last_completed_week(monday - 1) == monday - 2 * W
    assert last_completed_week(monday) == monday - W
    assert last_completed_week(monday + W - 1) == monday - W
    event = {'decision_ts': monday, 'side': 1}
    last = monday - W
    weeks = {(s, last - i * W): {'status': 'verified', 'week_end_exclusive': last - i * W + W,
                                 'official_ohlc': {'close': 100.0 if i else 101.0}}
             for s in ('BTCUSDT', 'ETHUSDT') for i in range(29)}
    assert gate(event, weeks)['week_gate'] is True
    weeks[('BTCUSDT', monday)] = {'status': 'verified', 'week_end_exclusive': monday + W, 'official_ohlc': {'close': 0.01}}
    assert gate(event, weeks)['week_gate'] is True
    assert gate({**event, 'side': -1}, weeks)['week_gate'] is False
    weeks[('ETHUSDT', last)]['official_ohlc']['close'] = 99.0
    assert gate(event, weeks)['week_gate'] is False
    weeks[('ETHUSDT', last)]['official_ohlc']['close'] = 100.0
    assert gate(event, weeks)['week_gate'] is False  # exactly equal to SMA
    del weeks[('BTCUSDT', last - 28 * W)]
    assert gate(event, weeks)['week_gate'] is None
    weeks[('BTCUSDT', last - 28 * W)] = {'status': 'unknown', 'week_end_exclusive': last - 27 * W, 'official_ohlc': {'close': 100}}
    assert gate(event, weeks)['week_gate'] is None
    checks = {'all_checks_pass': True, 'tests': ['monday_boundary', 'future_ignored', 'opposite_direction',
               'two_markets', 'strict_equality', 'missing_week', 'unverified_week'],
              'gate_code_sha256': sha(H / 'week_gate.py'), 'test_code_sha256': sha(Path(__file__))}
    (H / '周线时间与边界测试.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print('WEEK_GATE_TESTS', checks, flush=True)


if __name__ == '__main__':
    main()
