"""Is 30-day OI growth additive to 30-day price momentum, or the same thing?

oi_chg30 splits the strategy's P&L 9% / 38% / 65% a year, monotonically, in both
halves -- and it does so while holding LESS (34% of days in the bottom tercile vs
27% in the top), so it is not a look-through exposure effect. Every other
positioning feature failed that test.

The obvious objection: in a bull market price and open interest rise together, so
"OI is growing" may just mean "we are in the uptrend that the signal already
detects". If so the split is circular.

So: correlate the two, then double-sort. If OI growth still separates P&L inside
buckets of identical price momentum, it is new information.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oi_3 import build
from lev import D

pd.set_option("display.width", 220)


def integrity(sym="BTCUSDT"):
    """OI series sanity: level jumps, stale stretches, and unit drift."""
    m = pd.read_parquet(D / "metrics" / f"{sym}-metrics-5m.parquet")
    oi = m["sum_open_interest"].resample("1D").last()
    val = m["sum_open_interest_value"].resample("1D").last()
    j = oi.pct_change()
    print("\n===== OI series integrity =====")
    print(f"range {oi.index.min().date()} -> {oi.index.max().date()}  n={len(oi)}")
    print(f"level: min {oi.min():.0f}  max {oi.max():.0f}  last {oi.iloc[-1]:.0f}")
    print(f"daily chg: std {j.std()*100:.2f}%  p1 {j.quantile(.01)*100:.1f}%  "
          f"p99 {j.quantile(.99)*100:.1f}%  max {j.max()*100:.1f}%  min {j.min()*100:.1f}%")
    big = j.abs().sort_values(ascending=False).head(8)
    print("largest single-day jumps:")
    print((big * 100).round(1).to_string())
    # implied price should track the real price; a break means a unit change
    implied = val / oi
    c = pd.read_parquet(D / "perp" / f"k1h_{sym}.parquet")
    c["day"] = pd.to_datetime(c["dt"], utc=True).dt.normalize()
    px = c.groupby("day")["close"].last()
    ratio = (implied / px.reindex(implied.index)).dropna()
    print(f"implied/actual price ratio: median {ratio.median():.4f}  "
          f"p1 {ratio.quantile(.01):.4f}  p99 {ratio.quantile(.99):.4f}")
    print("(a ratio pinned near 1.0 means OI is quoted in coins and value in USD consistently)")


def corr_and_double(d):
    d = d.copy()
    # lag the conditioner one day: see oi_3.tercile for why
    d["oi_chg30"] = d["oi_chg30"].shift(1)
    d["px_chg30"] = d["px_chg30"].shift(1)
    t = d[["oi_chg30", "px_chg30", "pnl", "w"]].dropna()
    print("\n===== correlation =====")
    print(t[["oi_chg30", "px_chg30"]].corr().round(3).to_string())
    print(f"n={len(t)}")

    print("\n===== double sort: strategy P&L (ann %) by px_chg30 x oi_chg30 =====")
    t = t.copy()
    t["pb"] = pd.qcut(t["px_chg30"], 3, labels=["px low", "px mid", "px high"])
    t["ob"] = pd.qcut(t["oi_chg30"], 3, labels=["oi low", "oi mid", "oi high"])
    pv = t.pivot_table(index="pb", columns="ob", values="pnl",
                       aggfunc=lambda s: s.mean() * 365 * 100, observed=True)
    cnt = t.pivot_table(index="pb", columns="ob", values="pnl", aggfunc="size", observed=True)
    ex = t.pivot_table(index="pb", columns="ob", values="w", aggfunc="mean", observed=True) * 100
    print("annualised P&L:")
    print(pv.round(1).to_string())
    print("\ncell counts:")
    print(cnt.to_string())
    print("\nmean exposure %:")
    print(ex.round(1).to_string())

    # within each price bucket, the OI spread
    print("\nOI spread inside each price bucket (ann pp, high - low):")
    for pb in pv.index:
        row = pv.loc[pb]
        print(f"  {pb}: {row.iloc[-1] - row.iloc[0]:+.0f}pp   "
              f"(n={int(cnt.loc[pb].sum())})")


def main():
    integrity()
    d = build("BTCUSDT")
    d = d.loc[d.index >= "2020-03-01"]
    corr_and_double(d)

    # does the same hold on ETH?
    print("\n########## ETH ##########")
    try:
        e = build("ETHUSDT")
        e = e.loc[e.index >= "2020-03-01"]
        corr_and_double(e)
    except Exception as ex:
        print("ETH failed:", type(ex).__name__, ex)


if __name__ == "__main__":
    main()
