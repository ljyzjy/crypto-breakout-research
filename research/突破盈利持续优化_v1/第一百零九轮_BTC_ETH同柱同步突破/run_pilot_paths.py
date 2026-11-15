"""Build frozen three-day tick paths; no net PnL until official risk settlement."""
from __future__ import annotations

import csv
import hashlib
import heapq
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
P = H.parent
DATA = Path("D:/CodexResearch_2022_firstsec_20261115_v1")
R98 = P / "第九十八轮_二零二二原始逐笔全样本"
sys.path.insert(0, str(R98))
import run_raw_2022 as bulk
spec = importlib.util.spec_from_file_location("dual_engine_109", H / "dual_pilot_engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
Q, M = 900000, 60000
SYMS = ("BTCUSDT", "ETHUSDT")


def load_features(symbol):
    frame = pd.read_parquet(DATA / "normalized" / f"{symbol}_klines.parquet",
                            columns=["ts", "open", "high", "low", "close", "volume", "trade_count"])
    assert frame.ts.is_unique and frame.ts.is_monotonic_increasing
    minute = frame.set_index("ts")
    frame["quarter"] = frame.ts // Q * Q
    q = frame.groupby("quarter", sort=True).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"), n=("ts", "size"))
    assert q.n.eq(15).all()
    previous_close = q.close.shift(1)
    true_range = pd.concat([q.high - q.low, (q.high - previous_close).abs(), (q.low - previous_close).abs()], axis=1).max(axis=1)
    q["atr14"] = true_range.shift(1).rolling(14, min_periods=14).mean()
    q["upper"] = q.high.shift(1).rolling(16, min_periods=16).max()
    q["lower"] = q.low.shift(1).rolling(16, min_periods=16).min()
    return minute, q


def minute_matches(ticks, official, quarter):
    by = {}
    for t, ident, price, qty, maker in ticks:
        if quarter <= t < quarter + Q:
            key = (int(t) // M) * M
            value = float(price)
            if key not in by:
                by[key] = [value, value, value, value]
            else:
                x = by[key]
                x[1], x[2], x[3] = max(x[1], value), min(x[2], value), value
    failures = []
    for ts in range(quarter, quarter + Q, M):
        if ts not in official.index or ts not in by:
            failures.append({"ts": ts, "reason": "missing_minute"})
            continue
        row = official.loc[ts]
        expected = [float(row.open), float(row.high), float(row.low), float(row.close)]
        if not all(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-10) for a, b in zip(by[ts], expected)):
            failures.append({"ts": ts, "reason": "minute_ohlc_disagreement", "raw": by[ts], "official": expected})
    return failures


def symbol_events(symbol, ticks):
    for row in ticks:
        yield row[0], symbol, row[1], row[2]


def main():
    bulk.runner.guard(start=True)
    frozen = json.loads((H / "三日试点冻结.json").read_text(encoding="utf-8"))
    assert frozen["code_sha256"] == bulk.sha(H / "freeze_pilot.py")
    for name, digest in frozen["files"].items():
        assert bulk.sha(H / name) == digest
    minute_frozen = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    for name, digest in minute_frozen["files"].items():
        assert bulk.sha(name) == digest
    source = json.loads((H / "三日逐笔档来源.json").read_text(encoding="utf-8"))
    assert source["frozen_sha256"] == bulk.sha(H / "三日试点冻结.json") and source["code_sha256"] == bulk.sha(H / "fetch_pilot.py")
    archives = {(r["symbol"], r["day"]): r for r in source["archives"]}
    assert len(archives) == 6
    for record in archives.values():
        if record["status"] == "verified":
            assert bulk.sha(record["path"]) == record["sha256"]
    with (H / "分钟可能候选.csv").open(encoding="utf-8", newline="") as f:
        candidate_rows = [r for r in csv.DictReader(f) if r["day_utc"] in frozen["days"]]
    quarters = {}
    for r in candidate_rows:
        quarters.setdefault((r["day_utc"], int(r["quarter_ts"])), []).append(r)
    minute, features = {}, {}
    for symbol in SYMS:
        bulk.runner.guard()
        minute[symbol], features[symbol] = load_features(symbol)
    output, paths = [], []
    fingerprint = hashlib.sha256((bulk.sha(H / "三日试点冻结.json") + bulk.sha(H / "三日逐笔档来源.json") + bulk.sha(Path(__file__))).encode()).hexdigest()
    checkpoint_dir = DATA / "dual_2022_pilot_path_checkpoints"
    assert checkpoint_dir.resolve().is_relative_to(DATA.resolve())
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for (day, quarter), candidates in sorted(quarters.items()):
        bulk.runner.guard()
        key = hashlib.sha256((fingerprint + "|" + str(quarter)).encode()).hexdigest()
        checkpoint = checkpoint_dir / (key + ".json")
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            assert saved["fingerprint"] == fingerprint and saved["quarter_ts"] == quarter
            output.append(saved["signal"])
            paths.extend(saved["paths"])
            print("EXT109_PILOT_QUARTER", len(output), "/", len(quarters), day, "cached", flush=True)
            continue

        def save(record, group_paths):
            tmp = checkpoint.with_suffix(".partial")
            tmp.write_text(json.dumps({"fingerprint": fingerprint, "quarter_ts": quarter, "signal": record, "paths": group_paths},
                                      ensure_ascii=False, allow_nan=False), encoding="utf-8")
            tmp.replace(checkpoint)

        record = {"day": day, "quarter_ts": quarter, "screen_directions": [int(x["direction"]) for x in candidates]}
        day_start = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)
        if quarter - 2000 < day_start or quarter + Q + M > day_start + 24 * 3600 * 1000:
            record.update(status="unknown_cross_day_archive")
            output.append(record)
            save(record, [])
            continue
        if any(archives.get((sym, day), {}).get("status") != "verified" for sym in SYMS):
            record.update(status="unknown_archive")
            output.append(record)
            save(record, [])
            continue
        streams, failure = {}, []
        try:
            for symbol in SYMS:
                a = archives[(symbol, day)]
                streams[symbol] = bulk.raw.read_window(a["path"], "trades", quarter - 2000, quarter + Q + M)
                problems = minute_matches(streams[symbol], minute[symbol], quarter)
                if problems:
                    failure.append({"symbol": symbol, "problems": problems})
        except Exception as exc:
            if "headroom" in str(exc):
                raise
            record.update(status="unknown_raw_window", error=type(exc).__name__ + ":" + str(exc)[:180])
            output.append(record)
            save(record, [])
            continue
        if failure:
            record.update(status="unknown_minute_ohlc", issues=failure)
            output.append(record)
            save(record, [])
            continue
        levels, atr = {}, {}
        for symbol in SYMS:
            x = features[symbol].loc[quarter]
            levels[symbol] = {"upper": float(x.upper), "lower": float(x.lower)}
            atr[symbol] = float(x.atr14)
            assert np.isfinite([x.upper, x.lower, x.atr14]).all() and x.upper > x.lower and x.atr14 > 0
        for c in candidates:
            direction = int(c["direction"])
            assert math.isclose(float(c["btc_level"]), levels["BTCUSDT"]["upper" if direction == 1 else "lower"], rel_tol=1e-12)
            assert math.isclose(float(c["eth_level"]), levels["ETHUSDT"]["upper" if direction == 1 else "lower"], rel_tol=1e-12)
        event_iters = [symbol_events(sym, streams[sym]) for sym in SYMS]
        events = heapq.merge(*event_iters, key=lambda z: (z[0], z[1], z[2]))
        signal = engine.find_sync(events, levels, quarter, quarter + Q)
        if signal.get("side") is not None:
            assert int(signal["side"]) in record["screen_directions"]
        record.update(**signal, levels=levels, atr14=atr)
        before = len(paths)
        if signal["status"] == "confirmed":
            for symbol in SYMS:
                ticks = [(r[0], r[1], r[2]) for r in streams[symbol]]
                for lev in (10, 20):
                    for target in (1, 2):
                        path = engine.simulate_path(ticks, signal, levels, symbol, atr[symbol], lev, target, quarter + Q)
                        paths.append({"observation_id": f"dual|{quarter}|{symbol}", "contract": symbol, "leverage": lev,
                                      "target_r": target, "quarter_ts": quarter, **path})
        output.append(record)
        save(record, paths[before:])
        print("EXT109_PILOT_QUARTER", len(output), "/", len(quarters), day, signal["status"], flush=True)
    result = {"days": frozen["days"], "candidate_quarters": len(quarters), "signals": output, "paths": paths,
              "frozen_sha256": bulk.sha(H / "三日试点冻结.json"), "archive_source_sha256": bulk.sha(H / "三日逐笔档来源.json"),
              "engine_sha256": bulk.sha(H / "dual_pilot_engine.py"), "code_sha256": bulk.sha(Path(__file__)),
              "note": "Raw trigger and price paths only; funding/mark liquidation and independent audit not completed."}
    (H / "三日逐笔路径.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("EXT109_PATHS_COMPLETE", len(output), len(paths), flush=True)


if __name__ == "__main__":
    main()
