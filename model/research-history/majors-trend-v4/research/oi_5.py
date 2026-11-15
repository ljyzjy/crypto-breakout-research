"""Is oi_pct a crowding signal, or just the calendar?

Open interest rose from 39k BTC (2020-09) to 101k (2026), so a 365-day percentile of
it drifts upward with time. The strategy also decays over time (Sharpe 1.45 in the
first half, 1.04 in the second). Those two facts alone would produce the tercile
split we just saw: low oi_pct = early sample = the good years.

So before any leverage overlay, three checks:
  1. mean oi_pct by calendar year -- if it climbs, the tercile is a time sort
  2. terciles computed WITHIN each year -- does the effect exist inside a year
  3. a competing conditioner that has nothing to do with OI: price percentile
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oi_3 import build

pd.set_option("display.width", 220)


def time_check(d):
    print("\n===== mean oi_pct by year =====")
    g = d.groupby(d.index.year).agg(oi_pct=("oi_pct", "mean"),
                                    oi=("oit", "mean"),
                                    px=("close", "mean"),
                                    pnl=("pnl", "mean"),
                                    days=("pnl", "size"))
    g["ann%"] = g.pnl * 365 * 100
    print(g.round(2).to_string())
    r = d[["oi_pct"]].dropna()
    r["t"] = np.arange(len(r))
    print(f"\ncorr(oi_pct, time) = {r.oi_pct.corr(r.t):.3f}")


def within_year(d, f="oi_pct", nb=3):
    """Condition on the percentile of f *inside its own year*."""
    t = d[[f, "pnl", "w"]].dropna().copy()
    t["yr"] = t.index.year
    parts = []
    for y, g in t.groupby("yr"):
        if len(g) < 200:
            continue
        g = g.copy()
        g["rank"] = g[f].rank(pct=True)
        g["b"] = pd.cut(g["rank"], nb, labels=False)
        parts.append(g)
    t = pd.concat(parts)
    print(f"\n===== {f}: terciles computed WITHIN each year =====")
    rows = []
    for b, g in t.groupby("b"):
        rows.append(dict(b=int(b), n=len(g), ann=g.pnl.mean() * 365 * 100,
                         shp=g.pnl.mean() / g.pnl.std() * np.sqrt(365),
                         expo=g.w.mean() * 100))
    out = pd.DataFrame(rows)
    print(out.round(2).to_string(index=False))
    print(f"spread = {out.ann.iloc[-1] - out.ann.iloc[0]:+.0f}pp")
    return out


def by_year_table(d, f="oi_pct"):
    """Does the tercile ordering hold in each individual year?"""
    t = d[[f, "pnl"]].dropna().copy()
    t["yr"] = t.index.year
    rows = {}
    for y, g in t.groupby("yr"):
        if len(g) < 200:
            continue
        q = pd.qcut(g[f], 3, labels=False, duplicates="drop")
        rows[y] = g.groupby(q)["pnl"].mean() * 365 * 100
    out = pd.DataFrame(rows).T
    out.columns = ["low", "mid", "high"]
    out["low-high"] = out["low"] - out["high"]
    print(f"\n===== {f}: annualised P&L (ann %) by tercile, year by year =====")
    print(out.round(1).to_string())
    pos = (out["low-high"] > 0).sum()
    print(f"years where low > high: {pos} of {len(out)}")


def competing(d):
    """Price percentile over the same window: same shape, no OI needed."""
    d = d.copy()
    d["px_pct"] = d["close"].rolling(365, min_periods=120).rank(pct=True)
    for f in ["px_pct", "oi_pct"]:
        t = d[[f, "pnl", "w"]].dropna()
        r = t.copy()
        r[f] = r[f].shift(1)
        r = r.dropna()
        r["b"] = pd.qcut(r[f], 3, labels=False, duplicates="drop")
        g = r.groupby("b").agg(n=("pnl", "size"), ann=("pnl", lambda s: s.mean() * 365 * 100),
                               expo=("w", lambda s: s.mean() * 100))
        print(f"\n----- {f} tercile -----")
        print(g.round(1).to_string())
        print(f"spread = {g.ann.iloc[-1] - g.ann.iloc[0]:+.0f}pp")
    print(f"\ncorr(oi_pct, px_pct) = {d[['oi_pct', 'px_pct']].corr().iloc[0, 1]:.3f}")


def main():
    d = build("BTCUSDT").loc[lambda x: x.index >= "2020-09-01"]
    time_check(d)
    within_year(d, "oi_pct")
    by_year_table(d, "oi_pct")
    competing(d)


if __name__ == "__main__":
    main()
