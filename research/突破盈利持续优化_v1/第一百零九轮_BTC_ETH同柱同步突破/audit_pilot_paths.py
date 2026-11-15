"""Independent raw-parser replay of six frozen pilot quarters."""
from __future__ import annotations

from decimal import Decimal as D
import heapq
import importlib.util
from itertools import groupby
import json
import math
from pathlib import Path
import sys

import pandas as pd
import requests

H = Path(__file__).resolve().parent
P = H.parent
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
DATA = Path("D:/CodexResearch_2022_firstsec_20261115_v1")
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
sys.path.insert(0, str(bulk.R93))
import audit_raw_samples
M, Q = 60000, 900000
SYMS = ("BTCUSDT", "ETHUSDT")


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)


def recalc_features(frame, quarter):
    segments = []
    for offset in range(16, 0, -1):
        begin = quarter - offset * Q
        x = frame.loc[begin:begin + Q - M]
        assert len(x) == 15 and list(x.index) == list(range(begin, begin + Q, M))
        segments.append({"high": float(x.high.max()), "low": float(x.low.min()), "close": float(x.close.iloc[-1])})
    high = max(x["high"] for x in segments)
    low = min(x["low"] for x in segments)
    ranges = []
    for i in range(2, 16):
        x, prev = segments[i], segments[i - 1]["close"]
        ranges.append(max(x["high"] - x["low"], abs(x["high"] - prev), abs(x["low"] - prev)))
    return high, low, sum(ranges) / 14


def independent_sync(streams, levels, start, end):
    def rows(symbol):
        for x in streams[symbol]:
            yield (int(x[0]), symbol, int(x[1]), D(str(x[2])))
    merged = heapq.merge(*(rows(s) for s in SYMS), key=lambda x: (x[0], x[1], x[2]))
    last = {}
    trigger = None
    for ts, group in groupby(merged, key=lambda x: x[0]):
        for _, sym, _, price in group:
            last[sym] = (ts, price)
        tick = ts + 1
        if tick < start or tick >= end or any(s not in last or tick - last[s][0] > 2000 for s in SYMS):
            continue
        values = {s: last[s][1] for s in SYMS}
        if trigger is None:
            longs = all(values[s] > D(str(levels[s]["upper"])) for s in SYMS)
            shorts = all(values[s] < D(str(levels[s]["lower"])) for s in SYMS)
            if longs or shorts:
                trigger = {"signal_ts": tick, "side": 1 if longs else -1, "signal_prices": {s: str(values[s]) for s in SYMS}}
            continue
        if tick < trigger["signal_ts"] + 1000:
            continue
        if tick > trigger["signal_ts"] + 3000:
            return {"status": "unknown_confirmation", **trigger}
        side = trigger["side"]
        outside = all(D(side) * (values[s] - D(str(levels[s]["upper" if side == 1 else "lower"]))) > 0 for s in SYMS)
        return {"status": "confirmed" if outside else "confirmation_rejected", **trigger,
                "reference_ts": tick, "reference_prices": {s: str(values[s]) for s in SYMS}}
    return {"status": "unknown_confirmation", **trigger} if trigger else {"status": "no_sync"}


def independent_path(ticks, signal, levels, symbol, atr, lev, target_r, end):
    side = D(signal["side"])
    ref = D(signal["reference_prices"][symbol])
    atr = D(str(atr))
    level = D(str(levels[symbol]["upper" if side == 1 else "lower"]))
    ref_ts = int(signal["reference_ts"])
    if atr <= 0 or ref <= 0:
        return {"status": "unknown_invalid_atr_or_reference"}
    if ref_ts + 5000 >= end:
        return {"status": "no_order_time"}
    stop = level - side * atr / 2
    estimate = ref * (1 + side * D(".0005"))
    planned = side * (estimate - stop)
    safety = (D(1) / lev - D(".01")) / 2
    if stop <= 0 or planned <= 0 or planned > D("1.5") * atr or planned / estimate < D(".003") or planned / estimate + D(".003") >= safety:
        return {"status": "known_risk_rejected"}
    entry_index = next((i for i, x in enumerate(ticks) if x[0] >= ref_ts + 1000), None)
    if entry_index is None or ticks[entry_index][0] >= end:
        return {"status": "unknown_delayed_entry"}
    entry_tick = ticks[entry_index]
    entry = entry_tick[2] * (1 + side * D(".0005"))
    actual = side * (entry - stop)
    force = actual <= 0 or actual > D("1.5") * atr or actual / entry + D(".003") >= safety
    if force:
        exit_signal, reason = entry_tick[0], "filled_beyond_risk_budget"
    else:
        target = entry + side * target_r * actual
        stop_ts = target_ts = None
        for item in ticks[entry_index:]:
            if item[0] >= end:
                break
            if stop_ts is None and side * (item[2] - stop) <= 0:
                stop_ts = item[0]
            if target_ts is None and side * (item[2] - target) >= 0:
                target_ts = item[0]
        choices = [(end, 2, "quarter_time")]
        if stop_ts is not None:
            choices.append((stop_ts, 0, "stop"))
        if target_ts is not None:
            choices.append((target_ts, 1, "target"))
        exit_signal, _, reason = min(choices)
    fill = next((x for x in ticks if x[0] >= exit_signal + 5000), None)
    if fill is None:
        return {"status": "unknown_delayed_exit", "entry_ts": entry_tick[0], "exit_signal_ts": exit_signal}
    return {"status": "verified", "entry_ts": entry_tick[0], "entry_raw": entry_tick[2], "entry_fill": entry,
            "exit_signal_ts": exit_signal, "exit_ts": fill[0], "exit_raw": fill[2],
            "exit_fill": fill[2] * (1 - side * D(".0005")), "initial_stop": stop, "actual_entry_risk": actual, "reason": reason}


def main():
    bulk.runner.guard(start=True)
    frozen = json.loads((H / "逐笔独立样本冻结.json").read_text(encoding="utf-8"))
    assert frozen["pilot_freeze_sha256"] == bulk.sha(H / "三日试点冻结.json") and frozen["code_sha256"] == bulk.sha(H / "freeze_audit_sample.py")
    paths_file = H / "三日逐笔路径.json"
    data = json.loads(paths_file.read_text(encoding="utf-8"))
    assert data["frozen_sha256"] == bulk.sha(H / "三日试点冻结.json") and data["engine_sha256"] == bulk.sha(H / "dual_pilot_engine.py")
    assert data["code_sha256"] == bulk.sha(H / "run_pilot_paths.py") and data["archive_source_sha256"] == bulk.sha(H / "三日逐笔档来源.json")
    source = json.loads((H / "三日逐笔档来源.json").read_text(encoding="utf-8"))
    archives = {(r["symbol"], r["day"]): r for r in source["archives"]}
    for r in archives.values():
        if r["status"] == "verified":
            assert bulk.sha(r["path"]) == r["sha256"]
            ck = requests.get(r["url"] + ".CHECKSUM", timeout=(15, 50))
            ck.raise_for_status()
            parts = ck.text.strip().split()
            assert parts[0].lower() == r["sha256"] and Path(parts[1]).name == Path(r["path"]).name
    records = {int(r["quarter_ts"]): r for r in data["signals"]}
    paths = {(int(r["quarter_ts"]), r["contract"], int(r["leverage"]), int(r["target_r"])): r for r in data["paths"]}
    frames = {s: pd.read_parquet(DATA / "normalized" / f"{s}_klines.parquet").set_index("ts") for s in SYMS}
    checked = checked_paths = 0
    unresolved = []
    for quarter in frozen["sample_quarters"]:
        bulk.runner.guard()
        rec = records[quarter]
        if rec["status"].startswith("unknown_"):
            unresolved.append({"quarter_ts": quarter, "status": rec["status"]})
            continue
        levels, atr = {}, {}
        for s in SYMS:
            up, low, av = recalc_features(frames[s], quarter)
            assert close(up, rec["levels"][s]["upper"]) and close(low, rec["levels"][s]["lower"])
            assert close(av, rec["atr14"][s])
            levels[s], atr[s] = {"upper": up, "lower": low}, av
        streams = {}
        for s in SYMS:
            archive = archives[(s, rec["day"])]
            assert archive["status"] == "verified"
            streams[s] = audit_raw_samples.independent_window(archive["path"], "trades", quarter - 2000, quarter + Q + M)
            for ts in range(quarter, quarter + Q, M):
                values = [x[2] for x in streams[s] if ts <= x[0] < ts + M]
                assert values and ts in frames[s].index
                official = frames[s].loc[ts]
                for a, b in zip((values[0], max(values), min(values), values[-1]), (official.open, official.high, official.low, official.close)):
                    assert close(a, b)
        expected = independent_sync(streams, levels, quarter, quarter + Q)
        assert expected["status"] == rec["status"]
        for field in ("signal_ts", "side", "reference_ts"):
            if field in expected:
                assert int(expected[field]) == int(rec[field])
        for field in ("signal_prices", "reference_prices"):
            if field in expected:
                assert all(close(expected[field][s], rec[field][s]) for s in SYMS)
        if expected["status"] == "confirmed":
            for s in SYMS:
                for lev in (10, 20):
                    for target in (1, 2):
                        p = independent_path(streams[s], expected, levels, s, atr[s], lev, target, quarter + Q)
                        got = paths[(quarter, s, lev, target)]
                        assert p["status"] == got["status"]
                        if p["status"] == "verified":
                            assert p["reason"] == got["reason"]
                            for field in ("entry_ts", "exit_signal_ts", "exit_ts"):
                                assert int(p[field]) == int(got[field])
                            for field in ("entry_raw", "entry_fill", "exit_raw", "exit_fill", "initial_stop", "actual_entry_risk"):
                                assert close(p[field], got[field])
                        checked_paths += 1
        checked += 1
        print("EXT109_INDEPENDENT_SAMPLE", checked, "/6", quarter, rec["status"], flush=True)
    out = {"all_checks_pass": not unresolved, "samples_fixed": len(frozen["sample_quarters"]), "samples_checked": checked,
           "unresolved_samples": unresolved, "sample_paths_checked": checked_paths, "paths_sha256": bulk.sha(paths_file),
           "sample_freeze_sha256": bulk.sha(H / "逐笔独立样本冻结.json"), "code_sha256": bulk.sha(Path(__file__)),
           "note": "Independent chunk parser and scalar trigger/path reconstruction; sample only."}
    (H / "三日逐笔独立样本核验.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EXT109_PILOT_AUDIT", json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
