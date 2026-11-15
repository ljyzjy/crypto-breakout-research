"""One table to settle it: pooled vs within-year for every conditioning variable.

Pooling daily observations across years is what produced every false positive in
this session. A conditioner is only real if the ordering holds INSIDE a year, where
the market regime is roughly constant.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oi_3 import build

pd.set_option("display.width", 220)

FEATS = ["oi_pct", "oi_chg30", "div30", "tk30", "tlr_chg30", "fund_pct", "px_pct"]


def pooled(d, f, q=3):
    t = d[[f, "pnl", "w"]].dropna().copy()
    t[f] = t[f].shift(1)
    t = t.dropna()
    b = pd.qcut(t[f], q, labels=False, duplicates="drop")
    g = t.groupby(b).agg(ann=("pnl", lambda s: s.mean() * 365 * 100),
                         expo=("w", lambda s: s.mean() * 100))
    return g, t


def within_year(d, f, q=3):
    t = d[[f, "pnl", "w"]].dropna().copy()
    t[f] = t[f].shift(1)
    t = t.dropna()
    t["yr"] = t.index.year
    keep, year_spread = [], {}
    for y, g in t.groupby("yr"):
        if len(g) < 200:
            continue
        g = g.copy()
        g["b"] = pd.qcut(g[f], q, labels=False, duplicates="drop")
        keep.append(g)
        m = g.groupby("b")["pnl"].mean() * 365 * 100
        if len(m) == q:
            year_spread[y] = m.iloc[-1] - m.iloc[0]
    t2 = pd.concat(keep)
    g = t2.groupby("b").agg(ann=("pnl", lambda s: s.mean() * 365 * 100),
                            expo=("w", lambda s: s.mean() * 100))
    return g, year_spread


def main():
    d = build("BTCUSDT").loc[lambda x: x.index >= "2020-09-01"]
    d["px_pct"] = d["close"].rolling(365, min_periods=120).rank(pct=True)

    rows = []
    for f in FEATS:
        gp, tp = pooled(d, f)
        gw, ys = within_year(d, f)
        rows.append(dict(
            feat=f,
            pooled_lo=round(gp.ann.iloc[0], 0), pooled_hi=round(gp.ann.iloc[-1], 0),
            pooled_spread=round(gp.ann.iloc[-1] - gp.ann.iloc[0], 0),
            within_lo=round(gw.ann.iloc[0], 0), within_hi=round(gw.ann.iloc[-1], 0),
            within_spread=round(gw.ann.iloc[-1] - gw.ann.iloc[0], 0),
            yrs_consistent=f"{sum(v > 0 for v in ys.values())}/{len(ys)}",
            median_year_spread=round(float(np.median(list(ys.values()))), 0),
        ))
    out = pd.DataFrame(rows)
    print("\n===== strategy P&L (ann %) by tercile: pooled vs within-year =====")
    print("(yrs_consistent counts years where the pooled ordering repeats; 3/3 is required)")
    print(out.to_string(index=False))

    print("\n===== exposure in the high tercile (is it just more leverage?) =====")
    er = []
    for f in FEATS:
        gp, _ = pooled(d, f)
        gw, _ = within_year(d, f)
        er.append(dict(feat=f, pooled_expo_lo=round(gp.expo.iloc[0], 1),
                       pooled_expo_hi=round(gp.expo.iloc[-1], 1),
                       within_expo_lo=round(gw.expo.iloc[0], 1),
                       within_expo_hi=round(gw.expo.iloc[-1], 1)))
    print(pd.DataFrame(er).to_string(index=False))


if __name__ == "__main__":
    main()
