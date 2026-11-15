"""Download USDⓈ-M perpetual 1h klines + funding rate from data.binance.vision.

Needed because leverage and shorts only exist on perps, and both have real costs:
funding is paid on notional every 8h, and liquidation depends on the intraday path.
"""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

D = Path(__file__).resolve().parent / "data" / "perp"
D.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
START = pd.Timestamp("2019-09-01", tz="UTC")
END = pd.Timestamp("2026-11-01", tz="UTC")

KCOLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
         "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def months(a: pd.Timestamp, b: pd.Timestamp):
    cur = a.normalize().replace(day=1)
    while cur < b:
        yield cur.strftime("%Y-%m")
        cur = (cur + pd.offsets.MonthBegin(1)).normalize()


def get(url: str, tries: int = 4) -> bytes | None:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None


def monthly(kind: str, sym: str) -> pd.DataFrame:
    """kind: 'klines' with interval 1h, or 'fundingRate'."""
    parts = []
    for m in months(START, END):
        cache = D / f"{sym}-{kind}-{m}.csv"
        if cache.exists():
            parts.append(pd.read_csv(cache))
            continue
        if kind == "fundingRate":
            url = (f"https://data.binance.vision/data/futures/um/monthly/fundingRate/"
                   f"{sym}/{sym}-fundingRate-{m}.zip")
        else:
            url = (f"https://data.binance.vision/data/futures/um/monthly/klines/"
                   f"{sym}/1h/{sym}-1h-{m}.zip")
        raw = get(url)
        if raw is None:
            continue
        z = zipfile.ZipFile(io.BytesIO(raw))
        txt = z.read(z.namelist()[0])
        df = pd.read_csv(io.BytesIO(txt),
                         header=0 if b"open_time" in txt[:200] or b"calc_time" in txt[:200] else None)
        if kind == "klines":
            if df.shape[1] == len(KCOLS):
                df.columns = KCOLS
            else:
                df = pd.read_csv(io.BytesIO(txt), header=None, names=KCOLS[:df.shape[1]])
        else:
            if df.shape[1] != 3:
                df = pd.read_csv(io.BytesIO(txt), header=None,
                                 names=["calc_time", "funding_interval_hours", "last_funding_rate"])
        df.to_csv(cache, index=False)
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def to_dt(v: pd.Series) -> pd.Series:
    """Timestamps switched from ms to us in 2025 on this archive. Detect per value."""
    a = v.astype("int64").to_numpy()
    out = a.astype("float64")
    out = out / 1000.0
    # anything that still looks like microseconds after /1e3 -> divide again
    us = out > 4e12
    out[us] = out[us] / 1000.0
    return pd.to_datetime(out.astype("int64"), unit="ms", utc=True)


def main():
    k_all, f_all = [], []
    for sym in SYMBOLS:
        print("== klines", sym, flush=True)
        k = monthly("klines", sym)
        if k.empty:
            print("  no klines", flush=True)
            continue
        k["dt"] = to_dt(k["open_time"])
        for c in ("open", "high", "low", "close", "volume", "quote_volume", "trades"):
            k[c] = pd.to_numeric(k[c], errors="coerce")
        k = k[["dt", "open", "high", "low", "close", "volume", "quote_volume", "trades"]]
        k["symbol"] = sym
        k = k.dropna(subset=["close"]).drop_duplicates("dt").sort_values("dt")
        print(f"  {len(k)} rows  {k.dt.iloc[0]} -> {k.dt.iloc[-1]}", flush=True)
        k_all.append(k)

        print("== funding", sym, flush=True)
        f = monthly("fundingRate", sym)
        if f.empty:
            print("  no funding", flush=True)
            continue
        f["dt"] = to_dt(f["calc_time"])
        f["last_funding_rate"] = pd.to_numeric(f["last_funding_rate"], errors="coerce")
        f["funding_interval_hours"] = pd.to_numeric(f["funding_interval_hours"], errors="coerce").fillna(8)
        f["symbol"] = sym
        f = f.dropna(subset=["last_funding_rate"]).drop_duplicates("dt").sort_values("dt")
        print(f"  {len(f)} rows  {f.dt.iloc[0]} -> {f.dt.iloc[-1]}  "
              f"mean {f.last_funding_rate.mean()*1e4:.2f}bp", flush=True)
        f_all.append(f[["dt", "symbol", "funding_interval_hours", "last_funding_rate"]])

    if k_all:
        kk = pd.concat(k_all, ignore_index=True)
        kk.to_parquet(D / "perp_1h.parquet", index=False)
        print("saved perp_1h", kk.shape, flush=True)
    if f_all:
        ff = pd.concat(f_all, ignore_index=True)
        ff.to_parquet(D / "perp_funding.parquet", index=False)
        print("saved perp_funding", ff.shape, flush=True)

    meta = {}
    for sym in SYMBOLS:
        k = pd.concat(k_all, ignore_index=True)
        k = k[k.symbol == sym]
        meta[sym] = dict(rows=int(len(k)),
                         start=str(k.dt.min()), end=str(k.dt.max()))
    (D / "perp_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
