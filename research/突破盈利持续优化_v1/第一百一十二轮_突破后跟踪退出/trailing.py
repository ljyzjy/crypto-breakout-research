"""Causal 1R activation, 0.75R giveback exit on the original raw path."""
from bisect import bisect_left
from decimal import Decimal as D
from itertools import groupby


def apply(path, prices):
    start, baseline = int(path["entry_ts"]), int(path["exit_signal_ts"])
    if baseline <= start:
        return {"action": "original", "reason": "original_signal_first"}
    side, entry, risk = D(int(path["side"])), D(str(path["entry_fill"])), D(str(path["actual_entry_risk"]))
    if side not in (D(-1), D(1)) or entry <= 0 or risk <= 0:
        return {"action": "unknown", "reason": "invalid_actual_risk"}
    times = [int(x[0]) for x in prices]
    if any(a > b for a, b in zip(times, times[1:])):
        raise ValueError("unordered_trade_times")
    first = bisect_left(times, start)
    if first >= len(times) or times[first] != start:
        return {"action": "unknown", "reason": "missing_entry_reference"}
    if abs(D(str(prices[first][1])) - D(str(path["entry_raw"]))) > D("1e-9"):
        return {"action": "unknown", "reason": "entry_reference_mismatch"}
    original_fill = bisect_left(times, int(path["exit_ts"]))
    if (original_fill >= len(times) or times[original_fill] != int(path["exit_ts"])
            or abs(D(str(prices[original_fill][1])) - D(str(path["exit_raw"]))) > D("1e-9")):
        return {"action": "unknown", "reason": "original_exit_reference_mismatch"}
    end = bisect_left(times, baseline)
    best, active, signal = D(0), False, None
    for ts, group in groupby(prices[first:end], key=lambda x: int(x[0])):
        movements = [side * (D(str(x[1])) - entry) for x in group]
        if active and min(movements) <= best - D("0.75") * risk:
            signal = ts
            break
        best = max(best, max(movements))
        active = active or best >= risk
    if signal is None:
        return {"action": "original", "reason": "trailing_not_before_original"}
    fill = bisect_left(times, signal + 5000)
    if fill >= len(times):
        return {"action": "unknown", "reason": "missing_delayed_exit", "exit_signal_ts": signal}
    raw = D(str(prices[fill][1]))
    if raw <= 0:
        return {"action": "unknown", "reason": "invalid_exit_price", "exit_signal_ts": signal}
    return {"action": "trailing_exit", "reason": "activated_giveback", "exit_signal_ts": signal,
            "exit_ts": times[fill], "exit_raw": float(raw), "exit_fill": float(raw * (1 - side * D("0.0005")))}
