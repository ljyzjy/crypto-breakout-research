"""Download funding rate + premium index (basis) for a multi-coin carry universe.

Why these two series and nothing else:
  * funding is the cash flow the carry leg earns;
  * the premium index is the basis. A delta-neutral book's P&L is
    funding received minus the change in basis, so basis is not decoration --
    it is the entire risk of the trade.
Spot and perp klines are not needed: in a hedged book the two price legs cancel
and only their ratio (the basis) survives.
"""
from __future__ import annotations

import io
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import numpy as np

D = Path(__file__).resolve().parent / "data" / "carry"
D.mkdir(parents=True, exist_ok=True)

SYMBOLS = ("BTCUSDT ETHUSDT BNBUSDT XRPUSDT ADAUSDT SOLUSDT DOGEUSDT DOTUSDT "
           "LINKUSDT LTCUSDT BCHUSDT ETCUSDT TRXUSDT XLMUSDT ATOMUSDT EOSUSDT "
           "NEOUSDT FILUSDT AVAXUSDT UNIUSDT AAVEUSDT MATICUSDT NEARUSDT "
           "SANDUSDT AXSUSDT").split()

START, END = "2020-01", "2026-11"
BASE = "https://data.binance.vision/data/futures/um/monthly"


def months(a: str, b: str) -> list[str]:
    out, cur = [], pd.Timestamp(a + "-01")
    stop = pd.Timestamp(b + "-01")
    while cur < stop:
        out.append(cur.strftime("%Y-%m"))
        cur += pd.offsets.MonthBegin(1)
    return out


def get(url: str, tries: int = 3) -> bytes | None:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(0.8 * (i + 1))
        except Exception:
            time.sleep(0.8 * (i + 1))
    return None


def read_zip(raw: bytes, cols: list[str]) -> pd.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(raw))
    txt = z.read(z.namelist()[0])
    head = pd.read_csv(io.BytesIO(txt), nrows=1, header=None)
    has_header = not str(head.iloc[0, 0]).isdigit()
    df = pd.read_csv(io.BytesIO(txt), header=0 if has_header else None)
    if not has_header:
        df.columns = cols[: df.shape[1]]
    return df


def to_dt(v: pd.Series) -> pd.Series:
    """Archive timestamps are seconds, ms, or us depending on the year and file.

    Scale is unambiguous: seconds ~1.6e9, ms ~1.6e12, us ~1.6e15. Infer from
    magnitude per value, never from the file, because 2025 files mix both.
    """
    a = v.astype("int64").to_numpy().astype("float64")
    a = np.where(a < 1e11, a * 1000.0, a)          # seconds -> ms
    a = np.where(a > 1e14, a / 1000.0, a)          # us -> ms
    return pd.to_datetime(a.astype("int64"), unit="ms", utc=True)


def one_month(sym: str, m: str) -> tuple[str, str, pd.DataFrame | None, pd.DataFrame | None]:
    fund = prem = None
    f_cache = D / f"{sym}-funding-{m}.csv"
    p_cache = D / f"{sym}-prem-{m}.csv"
    if f_cache.exists():
        fund = pd.read_csv(f_cache)
    else:
        raw = get(f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
        if raw:
            fund = read_zip(raw, ["calc_time", "funding_interval_hours", "last_funding_rate"])
            fund.to_csv(f_cache, index=False)
    if p_cache.exists():
        prem = pd.read_csv(p_cache)
    else:
        raw = get(f"{BASE}/premiumIndexKlines/{sym}/1h/{sym}-1h-{m}.zip")
        if raw:
            prem = read_zip(raw, ["open_time", "open", "high", "low", "close", "volume",
                                  "close_time", "quote_volume", "count",
                                  "taker_buy_volume", "taker_buy_quote_volume", "ignore"])
            prem = prem[["open_time", "close"]]
            prem.to_csv(p_cache, index=False)
    return sym, m, fund, prem


def main():
    jobs = [(s, m) for s in SYMBOLS for m in months(START, END)]
    funds, prems = [], []
    with ThreadPoolExecutor(12) as ex:
        for i, (sym, m, f, p) in enumerate(ex.map(lambda a: one_month(*a), jobs), 1):
            if f is not None and len(f):
                f = f.copy()
                f["dt"] = to_dt(f["calc_time"])
                f["symbol"] = sym
                funds.append(f[["dt", "symbol", "funding_interval_hours", "last_funding_rate"]])
            if p is not None and len(p):
                p = p.copy()
                p["dt"] = to_dt(p["open_time"])
                p["symbol"] = sym
                prems.append(p[["dt", "symbol", "close"]].rename(columns={"close": "prem"}))
            if i % 400 == 0:
                print(f"  {i}/{len(jobs)} months done", flush=True)

    F = pd.concat(funds, ignore_index=True).drop_duplicates(["dt", "symbol"])
    F["last_funding_rate"] = pd.to_numeric(F["last_funding_rate"], errors="coerce")
    F = F.dropna(subset=["last_funding_rate"]).sort_values(["symbol", "dt"])

    P = pd.concat(prems, ignore_index=True).drop_duplicates(["dt", "symbol"])
    P["prem"] = pd.to_numeric(P["prem"], errors="coerce")

    F.to_parquet(D / "funding_long.parquet", index=False)
    P.to_parquet(D / "premium_long.parquet", index=False)

    print("\nsymbol  rows   start        end          ann_fund%  days")
    for s, g in F.groupby("symbol"):
        d = g.set_index("dt")["last_funding_rate"].resample("1D").sum()
        d = d.dropna()
        print(f"{s:9s} {len(g):6d} {g.dt.min().date()} {g.dt.max().date()} "
              f"{d.mean() * 365 * 100:9.2f} {len(d):5d}")
    print("\npremium rows", len(P), " funding rows", len(F))


if __name__ == "__main__":
    main()
