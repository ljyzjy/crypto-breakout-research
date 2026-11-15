"""Screen: cross-sectional momentum on the 24-coin panel.

The one thing never tested here. Everything so far was time-series on one asset.
Every multi-market CTA runs the cross-section too, and crypto is the one market where
the cross-section is still wide (24 names, dispersion >> BTC's own vol).

Standard applied before any backtest, per the rules established earlier:
  1. rank IC of the signal against the forward open-to-open return, per day, averaged,
     with a t-stat and a split-half
  2. per-year sign consistency
Only if that survives do we look at a P&L.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab

pd.set_option("display.width", 200)

C, O, H, L, V = lab.load_panel()
idx = C.index
r = C.pct_change()

valid = C.notna() & (V.fillna(0) > 0)
dv = V.rolling(30, min_periods=15).median()
uni = valid & (dv > 3e6) & (valid.cumsum() >= 250)
print(f"panel {C.shape[1]} coins, {idx.min().date()} -> {idx.max().date()}")
print(f"universe size per day: median {uni.sum(axis=1).median():.0f}, "
      f"min {uni.sum(axis=1).min():.0f}, max {uni.sum(axis=1).max():.0f}")

vol60 = r.rolling(60, min_periods=30).std()
# signal known at close(t); fill at open(t+1); hold to open(t+2).
# NOT O.shift(-1)/O-1: that window starts at open(t), i.e. before the signal exists,
# and it overlaps the day the momentum was measured on -> inflates IC mechanically.
fwd = O.shift(-2) / O.shift(-1) - 1
mkt = (r.where(uni).mean(axis=1))


def xrank(s):
    return s.where(uni).rank(axis=1, pct=True) - 0.5


def ic_series(sig):
    a = sig.where(uni)
    b = fwd.where(uni)
    t = pd.DataFrame({"a": a.stack(), "b": b.stack()}).dropna()
    if t.empty:
        return pd.Series(dtype=float)
    return t.groupby(level=0).apply(lambda g: g["a"].corr(g["b"], method="spearman"))


def ic_report(sig, name):
    ic = ic_series(sig)
    ic = ic[ic.notna()]
    n = len(ic)
    mu, sd = ic.mean(), ic.std()
    t = mu / sd * np.sqrt(n) if sd else np.nan
    half = n // 2
    h1, h2 = ic.iloc[:half].mean(), ic.iloc[half:].mean()
    yr = ic.groupby(ic.index.year).mean()
    pos = (yr > 0).sum()
    print(f"  {name:20s} IC {mu:+.4f}  t {t:+5.2f}  n {n:4d}  "
          f"half {h1:+.4f}/{h2:+.4f}  years+ {pos}/{len(yr)}  "
          f"IC_IR {mu / sd * np.sqrt(252):.2f}")
    return ic


print("\n===== rank IC vs forward 1-day return =====")
sigs = {}
for lb in (5, 10, 20, 40, 60, 90, 120, 180, 250):
    # risk-adjusted momentum: raw return divided by its own vol over the same window
    v = r.rolling(lb, min_periods=max(3, lb // 2)).std() * np.sqrt(lb)
    m = (C / C.shift(lb) - 1) / v.replace(0, np.nan)
    sigs[f"mom{lb}"] = m.clip(-4, 4)
    ic_report(xrank(m.clip(-4, 4)), f"mom{lb}")

print("\n----- multi-horizon blend (AQR style: equal risk across 1/3/12m) -----")
for combo, nm in [((20, 60, 120), "20/60/120"),
                  ((10, 30, 90, 180), "10/30/90/180"),
                  ((20, 40, 60, 90), "20/40/60/90 (current)")]:
    z = sum(((C / C.shift(n) - 1) / (r.rolling(n, min_periods=max(3, n // 2)).std()
                                     * np.sqrt(n)).replace(0, np.nan)).clip(-4, 4)
            for n in combo) / len(combo)
    sigs[nm] = z
    ic_report(xrank(z), nm)

print("\n===== monotonicity: forward return by cross-sectional rank decile =====")
for nm in ("mom20", "mom60", "20/60/120"):
    s = xrank(sigs[nm])
    q = np.ceil((s + 0.5) * 10)          # 1..10
    t = pd.DataFrame({"q": q.where(uni).stack(), "f": fwd.where(uni).stack()}).dropna()
    g = t.groupby("q")["f"].agg(n="size", mean=lambda x: x.mean() * 1e4,
                                med=lambda x: x.median() * 1e4,
                                win=lambda x: (x > 0).mean() * 100)
    g["mean_bp"] = g["mean"]
    print(f"\n{nm}: (bp per day, open-to-open)")
    print(g[["n", "mean_bp", "med", "win"]].round(2).to_string())

print("\n===== long-only vs short-only (top/bottom quintile) =====")
for nm in ("mom20", "mom60", "20/60/120"):
    s = xrank(sigs[nm])
    for lbl, sel in (("top 20%", s >= 0.4), ("bottom 20%", s <= -0.4)):
        f = fwd.where(uni & sel)
        m = f.mean(axis=1).dropna()
        m = m[m.index >= "2020-06-01"]
        print(f"  {nm:12s} {lbl:10s} mean {m.mean() * 1e4:+6.2f}bp  "
              f"ann {m.mean() * 365 * 100:+7.1f}%  win {(m > 0).mean() * 100:5.1f}%  "
              f"Sharpe {m.mean() / m.std() * np.sqrt(365):5.2f}")
