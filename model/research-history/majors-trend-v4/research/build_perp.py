"""Rebuild perp parquet from the cached monthly CSVs with correct timestamp units.

The archive switched from ms to us in 2025, so units must be detected per value,
not from the series max.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

D = Path(__file__).resolve().parent / "data" / "perp"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def to_dt(v: pd.Series) -> pd.Series:
    a = pd.to_numeric(v, errors="coerce").astype("float64").to_numpy().copy()
    us = a > 4e12          # 1.6e15 us vs 1.6e12 ms
    a[us] = a[us] / 1000.0
    return pd.to_datetime(pd.Series(a).astype("int64"), unit="ms", utc=True)


def build(sym: str) -> None:
    parts = []
    for f in sorted(glob.glob(str(D / f"{sym}-klines-*.csv"))):
        d = pd.read_csv(f)
        if d.shape[1] != 12:
            continue
        d.columns = COLS
        parts.append(d)
    if not parts:
        print(f"{sym}: no klines"); return
    k = pd.concat(parts, ignore_index=True)
    k["dt"] = to_dt(k["open_time"])
    for c in ("open", "high", "low", "close", "volume", "quote_volume", "trades"):
        k[c] = pd.to_numeric(k[c], errors="coerce")
    k = (k[["dt", "open", "high", "low", "close", "volume", "quote_volume", "trades"]]
         .dropna(subset=["close"]).drop_duplicates("dt").sort_values("dt"))
    k["symbol"] = sym
    k.to_parquet(D / f"k1h_{sym}.parquet", index=False)
    print(f"{sym} klines {k.shape} {k.dt.iloc[0]} -> {k.dt.iloc[-1]}")

    fparts = []
    for f in sorted(glob.glob(str(D / f"{sym}-fundingRate-*.csv"))):
        d = pd.read_csv(f)
        if d.shape[1] != 3:
            continue
        fparts.append(d)
    if not fparts:
        print(f"{sym}: no funding"); return
    fdf = pd.concat(fparts, ignore_index=True)
    fdf.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"]
    fdf["dt"] = to_dt(fdf["calc_time"])
    fdf["last_funding_rate"] = pd.to_numeric(fdf["last_funding_rate"], errors="coerce")
    fdf["funding_interval_hours"] = pd.to_numeric(
        fdf["funding_interval_hours"], errors="coerce").fillna(8)
    fdf = (fdf.dropna(subset=["last_funding_rate"]).drop_duplicates("dt")
              .sort_values("dt"))
    fdf["symbol"] = sym
    fdf[["dt", "symbol", "funding_interval_hours", "last_funding_rate"]].to_parquet(
        D / f"fnd_{sym}.parquet", index=False)
    mu = float(fdf["last_funding_rate"].mean())
    print(f"{sym} funding {fdf.shape} {fdf.dt.iloc[0]} -> {fdf.dt.iloc[-1]} "
          f"mean {mu*1e4:.2f}bp/8h = {mu*365*100:.1f}%/yr "
          f"pos {float((fdf.last_funding_rate>0).mean())*100:.0f}%")


if __name__ == "__main__":
    for s in ("BTCUSDT", "ETHUSDT"):
        build(s)
