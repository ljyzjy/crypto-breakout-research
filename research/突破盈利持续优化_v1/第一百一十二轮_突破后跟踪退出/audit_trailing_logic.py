"""Separate scalar trailing decision used with the independent raw parser."""
from decimal import Decimal as D
from itertools import groupby


def evaluate(path, seq):
    start, end = int(path["entry_ts"]), int(path["exit_signal_ts"])
    if end <= start:
        return "original", "original_signal_first", None, None
    side, entry, risk = int(path["side"]), D(str(path["entry_fill"])), D(str(path["actual_entry_risk"]))
    if side not in (-1, 1) or entry <= 0 or risk <= 0:
        return "unknown", "invalid_actual_risk", None, None
    first = next((x for x in seq if x[0] >= start), None)
    if first is None or first[0] != start:
        return "unknown", "missing_entry_reference", None, None
    if abs(first[2] - D(str(path["entry_raw"]))) > D("1e-9"):
        return "unknown", "entry_reference_mismatch", None, None
    orig_fill = next((x for x in seq if x[0] >= int(path["exit_ts"])), None)
    if orig_fill is None or orig_fill[0] != int(path["exit_ts"]) or abs(orig_fill[2] - D(str(path["exit_raw"]))) > D("1e-9"):
        return "unknown", "original_exit_reference_mismatch", None, None
    groups = groupby((x for x in seq if start <= x[0] < end), key=lambda x: x[0])
    best_price = entry
    active, target = False, None
    for _, g in groups:
        rows = list(g)
        threshold = best_price - D(side) * risk * D("0.75")
        if active and any(D(side) * (x[2] - threshold) <= 0 for x in rows):
            target = rows[0]
            break
        favorable = max(rows, key=lambda x: D(side) * x[2])[2]
        if D(side) * (favorable - best_price) > 0:
            best_price = favorable
        if D(side) * (best_price - entry) >= risk:
            active = True
    if target is None:
        return "original", "trailing_not_before_original", None, None
    fill = next((x for x in seq if x[0] >= target[0] + 5000), None)
    if fill is None:
        return "unknown", "missing_delayed_exit", target, None
    if fill[2] <= 0:
        return "unknown", "invalid_exit_price", target, fill
    return "trailing_exit", "activated_giveback", target, fill
