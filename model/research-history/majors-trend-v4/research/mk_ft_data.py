"""Convert the perp archive into freqtrade futures-format feather files.

Target paths (what idatahandler expects):
  user_data/data/binance/futures/BTC_USDT_USDT-1d-futures.feather
  user_data/data/binance/futures/BTC_USDT_USDT-8h-funding_rate.feather
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE = Path(r"C:\Users\WIN11\Documents\Codex\2026-11-12\ge\outputs\crypto-spot-kit\user_data\data\binance")
SRC = Path(r"C:\Users\WIN11\WorkBuddy\2026-11-14-00-04-30\strategy\data\perp")
DST = BASE / "futures"
DST.mkdir(parents=True, exist_ok=True)


def main():
    k = pd.read_parquet(SRC / "k1h_BTCUSDT.parquet")
    k["dt"] = pd.to_datetime(k["dt"], utc=True).dt.tz_convert(None)
    k["day"] = k["dt"].dt.normalize()
    d = (k.groupby("day").agg(open=("open", "first"), high=("high", "max"),
                              low=("low", "min"), close=("close", "last"),
                              volume=("volume", "sum"))
           .reset_index().rename(columns={"day": "date"}))
    d["date"] = pd.to_datetime(d["date"], utc=True)
    d = d[["date", "open", "high", "low", "close", "volume"]].sort_values("date")
    p1 = DST / "BTC_USDT_USDT-1d-futures.feather"
    d.reset_index(drop=True).to_feather(p1)
    print("1d futures", d.shape, d.date.iloc[0], "->", d.date.iloc[-1], p1.name)

    f = pd.read_parquet(SRC / "fnd_BTCUSDT.parquet")
    f["date"] = pd.to_datetime(f["dt"], utc=True).dt.tz_convert(None)
    f = f[["date", "last_funding_rate"]].rename(columns={"last_funding_rate": "funding_rate"})
    f["open"] = f["funding_rate"]
    f["high"] = f["funding_rate"]
    f["low"] = f["funding_rate"]
    f["close"] = f["funding_rate"]
    f["volume"] = 0.0
    f = f[["date", "open", "high", "low", "close", "volume", "funding_rate"]]
    f = f.sort_values("date").reset_index(drop=True)
    p2 = DST / "BTC_USDT_USDT-8h-funding_rate.feather"
    f.to_feather(p2)
    print("8h funding", f.shape, f.date.iloc[0], "->", f.date.iloc[-1], p2.name)
    print("unique hours:", sorted(pd.Series(f.date).dt.hour.unique().tolist())[:8])


if __name__ == "__main__":
    main()
