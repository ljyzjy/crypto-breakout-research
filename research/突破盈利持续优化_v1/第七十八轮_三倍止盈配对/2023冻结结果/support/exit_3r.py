"""Fixed 3R exit on an identical verified 2R one-second-observation entry."""
import numpy as np


def close(a, b):
    return bool(np.isclose(float(a), float(b), rtol=1e-11, atol=1e-12))


def decide(event, old, tape=None):
    if old['status'] != 'verified':
        return {'status': 'original_path_unverified'}
    fields = ('entry_ts', 'entry_raw', 'entry_fill', 'entry_signal_reference_ts', 'exit_signal_ts', 'exit_ts',
              'exit_raw', 'exit_fill', 'reason', 'initial_stop', 'fast_fail', 'actual_entry_risk')
    if old['reason'] in ('stop', 'quarter_time', 'filled_beyond_risk_budget'):
        return {'status': 'verified', **{k: old[k] for k in fields}, 'target_r': 3., 'source_mode': 'reuse_non_target'}
    if old['reason'] != 'target' or tape is None:
        return {'status': 'original_reason_or_tape_unknown'}
    t = tape.transact_time.to_numpy('int64')
    p = tape.price.to_numpy(float)
    side, quarter_end = int(event['side']), int(event['quarter_end'])
    if not len(t) or np.any(t[1:] < t[:-1]) or not np.isfinite(p).all() or (p <= 0).any():
        return {'status': 'invalid_tape'}
    ref = int(np.searchsorted(t, int(event['entry_exec_ts']), side='left'))
    if ref >= len(t) or int(t[ref]) != int(event['entry_exec_ts']) or not close(p[ref], event['raw_entry_1s']):
        return {'status': 'reference_disagreement'}
    entry_i = int(np.searchsorted(t, int(t[ref]) + 1000, side='left'))
    if entry_i >= len(t) or int(t[entry_i]) != int(old['entry_ts']) or not close(p[entry_i], old['entry_raw']):
        return {'status': 'entry_disagreement'}
    entry, stop = float(p[entry_i]) * (1 + side * .0005), float(old['initial_stop'])
    distance = side * (entry - stop)
    if distance <= 0 or not close(entry, old['entry_fill']):
        return {'status': 'entry_slippage_or_risk_disagreement'}
    end = int(np.searchsorted(t, quarter_end, side='right'))
    tt, pp = t[entry_i:end], p[entry_i:end]

    def trigger(target_multiple):
        target = entry + side * target_multiple * distance
        candidates = [(quarter_end, 2, 'quarter_time')]
        stops = np.flatnonzero(side * (pp - stop) <= 0)
        targets = np.flatnonzero(side * (pp - target) >= 0)
        if len(stops):
            candidates.append((int(tt[stops[0]]), 0, 'stop'))
        if len(targets):
            candidates.append((int(tt[targets[0]]), 1, 'target'))
        return min(candidates)[::2]

    old_signal, old_reason = trigger(2)
    if old_reason != 'target' or old_signal != int(old['exit_signal_ts']):
        return {'status': 'old_trigger_disagreement'}
    old_exit = int(np.searchsorted(t, old_signal + 5000, side='left'))
    if old_exit >= len(t) or int(t[old_exit]) != int(old['exit_ts']) or not close(p[old_exit], old['exit_raw']):
        return {'status': 'old_exit_disagreement'}
    signal, reason = trigger(3)
    if signal < old_signal:
        return {'status': 'exit_order_disagreement'}
    out_i = int(np.searchsorted(t, signal + 5000, side='left'))
    if out_i >= len(t):
        return {'status': 'missing_delayed_exit'}
    if int(t[out_i]) < int(old['exit_ts']):
        return {'status': 'exit_fill_order_disagreement'}
    raw = float(p[out_i])
    return {'status': 'verified', 'entry_ts': int(t[entry_i]), 'entry_raw': float(p[entry_i]), 'entry_fill': entry,
            'entry_signal_reference_ts': int(t[ref]), 'exit_signal_ts': signal, 'exit_ts': int(t[out_i]),
            'exit_raw': raw, 'exit_fill': raw * (1 - side * .0005), 'reason': reason,
            'initial_stop': stop, 'target_r': 3., 'fast_fail': False, 'actual_entry_risk': distance,
            'source_mode': 'replayed_old_target'}
