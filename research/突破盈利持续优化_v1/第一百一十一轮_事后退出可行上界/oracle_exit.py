"""Future-aware upper bound: fixed entry, stop, 5-second delay and zero funding."""
from bisect import bisect_left
from decimal import Decimal as D


def evaluate(path, ticks, quarter_end):
    side, entry = D(int(path["side"])), D(str(path["entry_fill"]))
    start, stop = int(path["entry_ts"]), D(str(path["initial_stop"]))
    if side not in (D(-1), D(1)) or entry <= 0 or stop <= 0:
        return {"status": "unknown_invalid_entry"}
    times = [int(x[0]) for x in ticks]
    if any(a > b for a, b in zip(times, times[1:])):
        raise ValueError("unordered_ticks")
    initial = bisect_left(times, start)
    if initial >= len(ticks) or times[initial] != start:
        return {"status": "unknown_entry_tick"}
    if abs(D(str(ticks[initial][1])) - D(str(path["entry_raw"]))) > D("1e-9"):
        return {"status": "unknown_entry_mismatch"}
    if path["reason"] == "filled_beyond_risk_budget":
        deadline = start
    else:
        breach = next((times[i] for i in range(initial, len(ticks))
                       if times[i] < quarter_end and side * (D(str(ticks[i][1])) - stop) <= 0), None)
        deadline = min(quarter_end, breach) if breach is not None else quarter_end
    forced_index = bisect_left(times, deadline + 5000)
    if forced_index >= len(ticks) or times[forced_index] >= quarter_end + 60000:
        return {"status": "unknown_forced_exit", "deadline_ts": deadline}
    first = bisect_left(times, start + 5000)
    # Every tick at/before deadline+5s can be the first tick after a pre-deadline
    # signal; the first tick after that threshold is the forced market fill.
    upper = bisect_left(times, deadline + 5001)
    candidates = list(range(first, upper))
    if forced_index not in candidates:
        candidates.append(forced_index)
    if not candidates:
        return {"status": "unknown_no_fill", "deadline_ts": deadline}

    def net(i):
        raw = D(str(ticks[i][1]))
        exit_ = raw * (1 - side * D(".0005"))
        return side * (exit_ - entry) / entry - D(".0005") * (1 + exit_ / entry)

    # With proportional exit fees and fixed adverse slippage, net is monotone
    # in side-adjusted raw exit price, so rank prices before one net calculation.
    best = max(candidates, key=lambda i: side * D(str(ticks[i][1])))
    return {"status": "known", "deadline_ts": deadline, "forced_exit_ts": times[forced_index],
            "oracle_exit_ts": times[best], "oracle_exit_raw": str(ticks[best][1]),
            "oracle_net": str(net(best)), "candidate_fill_count": len(candidates)}
