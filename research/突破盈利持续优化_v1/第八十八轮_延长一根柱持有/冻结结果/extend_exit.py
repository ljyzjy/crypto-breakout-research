"""Extend a verified original quarter-time exit by one further 15-minute bar."""
import math

EXTRA = 900000


def extend_path(old, tape):
    side, entry, stop = int(old['side']), float(old['entry_fill']), float(old['initial_stop'])
    qend, entry_ts = int(old['quarter_end']), int(old['entry_ts'])
    assert side in (-1, 1) and old['reason'] == 'quarter_time' and entry_ts < qend
    assert side * (entry - stop) > 0
    target = entry + side * 2 * (side * (entry - stop))
    assert tape and all(math.isfinite(p) and p > 0 for _, p in tape)
    assert all(tape[i][0] <= tape[i + 1][0] for i in range(len(tape) - 1))
    by_time = {}
    for ts, price in tape:
        if entry_ts <= ts <= qend + EXTRA:
            by_time.setdefault(int(ts), []).append(float(price))
    if not by_time or not any(t == entry_ts for t in by_time):
        return {'status': 'unknown_missing_entry_tick'}
    def first_trigger(lo, hi):
        for ts in sorted(t for t in by_time if lo <= t <= hi):
            prices = by_time[ts]
            if any(side * (p - stop) <= 0 for p in prices):
                return ts, 'stop'
            if any(side * (p - target) >= 0 for p in prices):
                return ts, 'target'
        return None
    if first_trigger(entry_ts, qend) is not None:
        return {'status': 'unknown_old_trigger_disagreement'}
    old_exit = next(((ts, px) for ts, px in tape if ts >= qend + 5000), None)
    if old_exit is None or old_exit[0] != int(old['exit_ts']) or not math.isclose(old_exit[1], float(old['exit_raw']), rel_tol=1e-11, abs_tol=1e-12):
        return {'status': 'unknown_old_exit_disagreement'}
    trigger = first_trigger(qend + 1, qend + EXTRA)
    signal, reason = trigger if trigger else (qend + EXTRA, 'extended_quarter_time')
    exit_ = next(((ts, px) for ts, px in tape if ts >= signal + 5000), None)
    if exit_ is None:
        return {'status': 'unknown_missing_extended_exit', 'exit_signal_ts': signal}
    return {'status': 'verified', 'entry_ts': entry_ts, 'entry_raw': float(old['entry_raw']),
            'entry_fill': entry, 'entry_signal_reference_ts': int(old['entry_signal_reference_ts']),
            'exit_signal_ts': signal, 'exit_ts': exit_[0], 'exit_raw': exit_[1],
            'exit_fill': exit_[1] * (1 - side * .0005), 'reason': reason, 'initial_stop': stop,
            'target_r': 2.0, 'actual_entry_risk': side * (entry - stop), 'extended_quarter_end': qend + EXTRA}
