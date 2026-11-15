"""Retrospective minute screen for possible simultaneous BTC/ETH breakout quarters."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import psutil

H = Path(__file__).resolve().parent
DATA = Path("D:/CodexResearch_2022_firstsec_20261115_v1")
SYS = H.parents[2]
Q = 900_000


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def guard(start=False):
    if shutil.disk_usage(SYS).free < 2_200_000_000:
        raise RuntimeError("system_disk_headroom")
    if shutil.disk_usage(DATA).free < 5_000_000_000:
        raise RuntimeError("data_disk_headroom")
    if psutil.virtual_memory().available < (850 if start else 300) * 1024**2:
        raise RuntimeError("memory_headroom")


def quarter_table(frame):
    required = ["ts", "open", "high", "low", "close", "volume", "trade_count"]
    assert all(k in frame for k in required)
    data = frame[required].copy()
    assert not data.ts.duplicated().any() and data.ts.is_monotonic_increasing
    assert ((data.ts % 60000) == 0).all()
    numeric = data[["open", "high", "low", "close", "volume", "trade_count"]].to_numpy(dtype=float)
    good = np.isfinite(numeric).all(axis=1)
    good &= (data[["open", "high", "low", "close"]].to_numpy(dtype=float) > 0).all(axis=1)
    good &= (data.high >= data[["open", "close", "low"]].max(axis=1))
    good &= (data.low <= data[["open", "close", "high"]].min(axis=1))
    good &= (data.volume >= 0) & (data.trade_count > 0)
    data["valid"] = good
    data["quarter"] = data.ts // Q * Q
    grouped = data.groupby("quarter", sort=True).agg(high=("high", "max"), low=("low", "min"),
                                                       minutes=("ts", "size"), valid_minutes=("valid", "sum"))
    grouped["valid"] = grouped.minutes.eq(15) & grouped.valid_minutes.eq(15)
    return grouped


def possible_quarters(btc, eth):
    assert btc.index.is_unique and eth.index.is_unique and btc.index.is_monotonic_increasing and eth.index.is_monotonic_increasing
    all_index = btc.index.union(eth.index).sort_values()
    b, e = btc.reindex(all_index), eth.reindex(all_index)
    # Reindex missing whole quarters so a gap cannot be silently compressed by rolling(16).
    all_index = pd.Index(np.arange(int(all_index.min()), int(all_index.max()) + Q, Q, dtype=np.int64), name="quarter")
    b, e = b.reindex(all_index), e.reindex(all_index)
    bv, ev = b.valid.fillna(False).astype(bool), e.valid.fillna(False).astype(bool)
    bh, bl = b.high.where(bv), b.low.where(bv)
    eh, el = e.high.where(ev), e.low.where(ev)
    out = pd.DataFrame(index=all_index)
    out["btc_upper"] = bh.shift(1).rolling(16, min_periods=16).max()
    out["btc_lower"] = bl.shift(1).rolling(16, min_periods=16).min()
    out["eth_upper"] = eh.shift(1).rolling(16, min_periods=16).max()
    out["eth_lower"] = el.shift(1).rolling(16, min_periods=16).min()
    out["known"] = bv & ev & out.notna().all(axis=1)
    out["possible_long"] = out.known & bh.gt(out.btc_upper) & eh.gt(out.eth_upper)
    out["possible_short"] = out.known & bl.lt(out.btc_lower) & el.lt(out.eth_lower)
    return out


def archive_present(symbol, date):
    name = f"{symbol}-trades-{date}.zip"
    return any((DATA / folder / name).is_file() for folder in
               ("raw_2022_full_trades", "same_phase_extra_raw", "independent_raw_trade_samples"))


def main():
    guard(start=True)
    f = json.loads((H / "输入冻结.json").read_text(encoding="utf-8"))
    assert f["freeze_code_sha256"] == sha(H / "freeze_inputs.py")
    for path, digest in f["files"].items():
        assert sha(Path(path)) == digest
    test = json.loads((H / "候选合成核验.json").read_text(encoding="utf-8"))
    assert test["all_checks_pass"] and test["code_sha256"] == sha(Path(__file__)) and test["test_sha256"] == sha(H / "test_screen.py")
    tables, sizes = {}, {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        guard()
        path = DATA / "normalized" / f"{symbol}_klines.parquet"
        frame = pd.read_parquet(path, columns=["ts", "open", "high", "low", "close", "volume", "trade_count"])
        sizes[symbol] = {"rows": len(frame), "invalid_quarters": None}
        tables[symbol] = quarter_table(frame)
        sizes[symbol]["invalid_quarters"] = int((~tables[symbol].valid).sum())
        del frame
    out = possible_quarters(tables["BTCUSDT"], tables["ETHUSDT"])
    start = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    out = out[(out.index >= start) & (out.index < end)]
    assert len(out) == 365 * 96
    rows, needed = [], set()
    for ts, r in out.iterrows():
        for direction, col in ((1, "possible_long"), (-1, "possible_short")):
            if not bool(r[col]):
                continue
            d = datetime.fromtimestamp(int(ts) / 1000, timezone.utc)
            day = d.date().isoformat()
            previous = (d.date() - timedelta(days=1)).isoformat() if d.hour == d.minute == 0 else None
            for sym in ("BTCUSDT", "ETHUSDT"):
                needed.add((sym, day))
                if previous:
                    needed.add((sym, previous))
            rows.append({"quarter_ts": int(ts), "day_utc": day, "direction": direction,
                         "btc_level": float(r["btc_upper"] if direction == 1 else r["btc_lower"]),
                         "eth_level": float(r["eth_upper"] if direction == 1 else r["eth_lower"]),
                         "btc_day_present_unverified": archive_present("BTCUSDT", day),
                         "eth_day_present_unverified": archive_present("ETHUSDT", day),
                         "previous_day_needed": previous or ""})
    import csv
    detail = H / "分钟可能候选.csv"
    columns = ["quarter_ts", "day_utc", "direction", "btc_level", "eth_level", "btc_day_present_unverified", "eth_day_present_unverified", "previous_day_needed"]
    with detail.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    needed_rows = [{"symbol": sym, "day": day, "present_unverified": archive_present(sym, day)} for sym, day in sorted(needed)]
    with (H / "逐笔档需求.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "day", "present_unverified"])
        w.writeheader()
        w.writerows(needed_rows)
    output = {"total_2022_quarters": len(out), "known_quarters": int(out.known.sum()), "unknown_quarters": int((~out.known).sum()),
              "possible_direction_rows": len(rows), "possible_quarters": int((out.possible_long | out.possible_short).sum()),
              "possible_long": int(out.possible_long.sum()), "possible_short": int(out.possible_short.sum()),
              "both_directions_possible_quarters": int((out.possible_long & out.possible_short).sum()),
              "candidate_dates": len({r["day_utc"] for r in rows}), "archive_files_needed": len(needed_rows),
              "archive_files_present_unverified": sum(r["present_unverified"] for r in needed_rows),
              "archive_files_missing": sum(not r["present_unverified"] for r in needed_rows),
              "source_quality": sizes, "detail_sha256": sha(detail), "archives_sha256": sha(H / "逐笔档需求.csv"),
              "frozen_sha256": sha(H / "输入冻结.json"), "code_sha256": sha(Path(__file__)),
              "note": "Retrospective OHLC superset only; no simultaneous tick confirmation or profit calculation."}
    (H / "分钟候选筛查.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
