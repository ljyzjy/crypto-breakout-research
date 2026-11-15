"""Signal-time BTC/ETH synchronous break and conservative delayed market path."""
from bisect import bisect_left
from decimal import Decimal as D
from itertools import groupby

SYMBOLS = ("BTCUSDT", "ETHUSDT")
FEE = D(".0005")
SLIP = D(".0005")


def find_sync(events, levels, begin, end):
    latest = {}
    signal = None
    last_ts = -1
    for ts, group in groupby(events, key=lambda x: x[0]):
        ts = int(ts)
        if ts < last_ts:
            raise ValueError("unordered_events")
        last_ts = ts
        for _, symbol, _, raw in group:
            assert symbol in SYMBOLS
            price = D(str(raw))
            if price <= 0:
                raise ValueError("nonpositive_price")
            latest[symbol] = (ts, price)
        now = ts + 1
        if now < begin or now >= end:
            continue
        if any(sym not in latest or now - latest[sym][0] > 2000 for sym in SYMBOLS):
            continue
        prices = {sym: latest[sym][1] for sym in SYMBOLS}
        if signal is None:
            up = all(prices[sym] > D(str(levels[sym]["upper"])) for sym in SYMBOLS)
            down = all(prices[sym] < D(str(levels[sym]["lower"])) for sym in SYMBOLS)
            assert not (up and down)
            if up or down:
                signal = {"signal_ts": now, "side": 1 if up else -1,
                          "signal_prices": {s: str(prices[s]) for s in SYMBOLS}}
            continue
        if now < signal["signal_ts"] + 1000:
            continue
        if now > signal["signal_ts"] + 3000:
            return {"status": "unknown_confirmation", **signal}
        side = signal["side"]
        stays = all(D(side) * (prices[s] - D(str(levels[s]["upper" if side == 1 else "lower"]))) > 0 for s in SYMBOLS)
        return {"status": "confirmed" if stays else "confirmation_rejected", **signal,
                "reference_ts": now, "reference_prices": {s: str(prices[s]) for s in SYMBOLS}}
    return {"status": "unknown_confirmation", **signal} if signal else {"status": "no_sync"}


def simulate_path(ticks, signal, levels, symbol, atr, leverage, target_r, quarter_end):
    assert signal["status"] == "confirmed" and symbol in SYMBOLS and leverage in (10, 20) and target_r in (1, 2)
    side = D(int(signal["side"]))
    atr = D(str(atr))
    level = D(str(levels[symbol]["upper" if side == 1 else "lower"]))
    ref = D(signal["reference_prices"][symbol])
    ref_ts = int(signal["reference_ts"])
    if atr <= 0 or ref <= 0:
        return {"status": "unknown_invalid_atr_or_reference"}
    if ref_ts + 5000 >= quarter_end:
        return {"status": "no_order_time"}
    stop = level - side * atr * D(".5")
    estimated = ref * (1 + side * SLIP)
    risk = side * (estimated - stop)
    safety = D(".5") * (D(1) / D(leverage) - D(".01"))
    if stop <= 0 or risk <= 0 or risk > D("1.5") * atr or risk / estimated < D(".003") or risk / estimated + D(".003") >= safety:
        return {"status": "known_risk_rejected", "initial_stop": str(stop)}
    times = [int(x[0]) for x in ticks]
    if any(a > b for a, b in zip(times, times[1:])):
        raise ValueError("unordered_ticks")
    i = bisect_left(times, ref_ts + 1000)
    if i >= len(ticks) or times[i] >= quarter_end:
        return {"status": "unknown_delayed_entry", "initial_stop": str(stop)}
    entry_ts, entry_raw = times[i], D(str(ticks[i][2]))
    entry = entry_raw * (1 + side * SLIP)
    actual_risk = side * (entry - stop)
    force = actual_risk <= 0 or actual_risk > D("1.5") * atr or actual_risk / entry + D(".003") >= safety
    target = entry + side * D(target_r) * actual_risk
    if force:
        exit_signal_ts, reason = entry_ts, "filled_beyond_risk_budget"
    else:
        stops = (times[j] for j in range(i, len(ticks)) if times[j] < quarter_end and side * (D(str(ticks[j][2])) - stop) <= 0)
        targets = (times[j] for j in range(i, len(ticks)) if times[j] < quarter_end and side * (D(str(ticks[j][2])) - target) >= 0)
        first_stop, first_target = next(stops, None), next(targets, None)
        choices = [(quarter_end, 2, "quarter_time")]
        if first_stop is not None:
            choices.append((first_stop, 0, "stop"))
        if first_target is not None:
            choices.append((first_target, 1, "target"))
        exit_signal_ts, _, reason = min(choices)
    out = bisect_left(times, exit_signal_ts + 5000)
    if out >= len(ticks):
        return {"status": "unknown_delayed_exit", "entry_ts": entry_ts, "exit_signal_ts": exit_signal_ts}
    exit_raw = D(str(ticks[out][2]))
    return {"status": "verified", "contract": symbol, "variant": f"dual_{target_r}r_{leverage}x", "side": int(side),
            "decision_ts": int(signal["signal_ts"]), "entry_signal_reference_ts": ref_ts,
            "entry_ts": entry_ts, "entry_raw": float(entry_raw), "entry_fill": float(entry),
            "exit_signal_ts": int(exit_signal_ts), "exit_ts": times[out], "exit_raw": float(exit_raw),
            "exit_fill": float(exit_raw * (1 - side * SLIP)), "initial_stop": float(stop),
            "actual_entry_risk": float(actual_risk), "target_r": target_r, "reason": reason, "quarter_end": int(quarter_end)}
