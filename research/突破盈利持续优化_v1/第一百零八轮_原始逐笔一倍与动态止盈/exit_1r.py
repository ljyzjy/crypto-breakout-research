"""Causal one-risk-unit target for an already established raw path."""
from bisect import bisect_left
from decimal import Decimal


def apply(path, prices):
    entry_ts = int(path["entry_ts"])
    baseline_ts = int(path["exit_signal_ts"])
    if baseline_ts <= entry_ts:
        return {"action": "original", "reason": "original_signal_first"}
    side = int(path["side"])
    entry = Decimal(str(path["entry_fill"]))
    risk = Decimal(str(path["actual_entry_risk"]))
    if side not in (-1, 1) or entry <= 0 or risk <= 0:
        return {"action": "unknown", "reason": "invalid_actual_risk"}
    times = [int(row[0]) for row in prices]
    if any(a > b for a, b in zip(times, times[1:])):
        raise ValueError("unordered_trade_times")
    first = bisect_left(times, entry_ts)
    if first >= len(times) or times[first] != entry_ts:
        return {"action": "unknown", "reason": "missing_entry_reference"}
    if "entry_raw" in path and abs(Decimal(str(prices[first][1])) - Decimal(str(path["entry_raw"]))) > Decimal("1e-9"):
        return {"action": "unknown", "reason": "entry_reference_mismatch"}
    if "exit_ts" in path and "exit_raw" in path:
        original_fill = bisect_left(times, int(path["exit_ts"]))
        if (original_fill >= len(times) or times[original_fill] != int(path["exit_ts"])
                or abs(Decimal(str(prices[original_fill][1])) - Decimal(str(path["exit_raw"]))) > Decimal("1e-9")):
            return {"action": "unknown", "reason": "original_exit_reference_mismatch"}
    original = bisect_left(times, baseline_ts)
    target = next((i for i in range(first, original)
                   if Decimal(side) * (Decimal(str(prices[i][1])) - entry) >= risk), None)
    if target is None:
        return {"action": "original", "reason": "one_r_not_before_original"}
    signal = times[target]
    fill = bisect_left(times, signal + 5000)
    if fill >= len(prices):
        return {"action": "unknown", "reason": "missing_delayed_exit", "exit_signal_ts": signal}
    raw = Decimal(str(prices[fill][1]))
    if raw <= 0:
        return {"action": "unknown", "reason": "invalid_exit_price", "exit_signal_ts": signal}
    return {"action": "one_r_exit", "reason": "one_r_target", "exit_signal_ts": signal,
            "exit_ts": times[fill], "exit_raw": float(raw),
            "exit_fill": float(raw * (Decimal(1) - Decimal(side) * Decimal(".0005")))}
