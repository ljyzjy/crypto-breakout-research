"""Download Binance USDⓈ-M 5-minute metrics: open interest, top-trader long/short
ratios, and taker long/short volume ratio.

This is the first data source in the project that is NOT a transform of OHLCV.
The whole point of pulling it is to run the direction filter (AUC on next-bar
sign) before writing any strategy: OHLCV-derived features all scored 0.486-0.502
and were rejected. If these also score 0.50, the conclusion generalises and we
stop; if something clears 0.52 out-of-sample, it is worth a backtest.
"""
from __future__ import annotations

import io
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BASE = "https://data.binance.vision/data/futures/um/daily/metrics"
D = Path(__file__).resolve().parent / "data" / "metrics"
D.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2026-11-10")
END = pd.Timestamp("2026-11-13")


def url(sym: str, day: str) -> str:
    return f"{BASE}/{sym}/{sym}-metrics-{day}.zip"


def grab(sym: str, day: str, tries: int = 3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url(sym, day), timeout=60) as r:
                b = r.read()
            z = zipfile.ZipFile(io.BytesIO(b))
            n = z.namelist()[0]
            df = pd.read_csv(z.open(n))
            return day, df
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return day, None
        except Exception:
            pass
    return day, None


def probe_first(sym: str) -> str:
    """Earliest day that exists, by bisection between 2019-09-01 and today."""
    lo, hi = pd.Timestamp("2019-09-01"), pd.Timestamp("2026-11-13")
    # first make sure the late end exists
    while hi > lo:
        mid = lo + (hi - lo) / 2
        _, df = grab(sym, mid.strftime("%Y-%m-%d"), tries=1)
        if df is not None:
            hi = mid
        else:
            lo = mid + pd.Timedelta(days=1)
    return lo.strftime("%Y-%m-%d")


def main():
    days = pd.date_range(START, END, freq="D").strftime("%Y-%m-%d").tolist()
    for sym in ["BTCUSDT", "ETHUSDT"]:
        out = D / f"{sym}-metrics-5m.parquet"
        if out.exists():
            print(f"{sym}: exists, skip")
            continue
        # how far back does it go?
        probe = grab(sym, "2020-01-01", tries=2)[1]
        first = "2020-01-01" if probe is not None else probe_first(sym)
        days = pd.date_range(first, END, freq="D").strftime("%Y-%m-%d").tolist()
        print(f"{sym}: {len(days)} days from {first}", flush=True)
        frames, miss, done = [], [], 0
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = {ex.submit(grab, sym, d): d for d in days}
            for f in as_completed(futs):
                d, df = f.result()
                done += 1
                if df is None:
                    miss.append(d)
                else:
                    frames.append(df)
                if done % 250 == 0:
                    print(f"  {done}/{len(days)}  miss={len(miss)}", flush=True)
        if not frames:
            print(f"{sym}: nothing downloaded")
            continue
        m = pd.concat(frames, ignore_index=True)
        m["ts"] = pd.to_datetime(m["create_time"], utc=True)
        m = (m.drop(columns=["create_time", "symbol"])
               .drop_duplicates("ts")
               .set_index("ts")
               .sort_index())
        for c in m.columns:
            m[c] = pd.to_numeric(m[c], errors="coerce")
        m.to_parquet(out)
        print(f"{sym}: saved {m.shape} {m.index.min()} -> {m.index.max()} "
              f"missing_days={len(miss)}", flush=True)


if __name__ == "__main__":
    main()
