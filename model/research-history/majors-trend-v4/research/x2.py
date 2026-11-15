"""Cross-sectional momentum, done at the horizon it is actually claimed to work.

The 1-day test is contaminated by microstructure reversal (IC -0.027). Momentum in a
multi-market CTA is a 1-4 week phenomenon: the book is rebalanced weekly or monthly, not
daily, and the short-horizon reversal is a separate (unexploitable) effect.

Non-overlapping sampling: for horizon h we take every h-th day, so the IC series has no
overlap and the t-stat is honest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab

pd.set_option("display.width", 220)

C, O, H, L, V = lab.load_panel()
r = C.pct_change()
valid = C.notna() & (V.fillna(0) > 0)
dv = V.rolling(30, min_periods=15).median()
uni = valid & (dv > 3e6) & (valid.cumsum() >= 250)


def xrank(s):
    return s.where(uni).rank(axis=1, pct=True) - 0.5


def mom(lb):
    v = r.rolling(lb, min_periods=max(3, lb // 2)).std() * np.sqrt(lb)
    return ((C / C.shift(lb) - 1) / v.replace(0, np.nan)).clip(-4, 4)


SIG = {f"mom{lb}": mom(lb) for lb in (5, 10, 20, 40, 60, 90, 120, 180)}
SIG["blend"] = sum(mom(n) for n in (10, 30, 90, 180)) / 4

print("IC by horizon (non-overlapping samples, open-to-open)")
print(f"{'sig':8s} " + " ".join(f"  h={h:<3d}" for h in (1, 3, 5, 7, 14, 21, 28)))
for nm, s in SIG.items():
    row = []
    for h in (1, 3, 5, 7, 14, 21, 28):
        f = O.shift(-(h + 1)) / O.shift(-1) - 1        # open(t+1) -> open(t+1+h)
        days = C.index[::h]
        a = xrank(s).reindex(days)
        b = f.reindex(days)
        t = pd.DataFrame({"a": a.stack(), "b": b.stack()}).dropna()
        if len(t) < 30:
            row.append("   n/a ")
            continue
        ic = t.groupby(level=0).apply(lambda g: g["a"].corr(g["b"], method="spearman"))
        ic = ic.dropna()
        tt = ic.mean() / ic.std() * np.sqrt(len(ic)) if ic.std() else np.nan
        row.append(f"{ic.mean():+.3f}/{tt:+5.1f}")
    print(f"{nm:8s} " + " ".join(row))

print("\n(IC / t-stat;  t>2 in |.| means real)")

print("\n===== same, but yearly IC for the best cell =====")
for nm, h, lb in (("mom60", 7, 60), ("mom120", 7, 120), ("blend", 7, 0), ("mom40", 14, 40)):
    f = O.shift(-(h + 1)) / O.shift(-1) - 1
    days = C.index[::h]
    s = SIG[nm]
    a, b = xrank(s).reindex(days), f.reindex(days)
    t = pd.DataFrame({"a": a.stack(), "b": b.stack()}).dropna()
    ic = t.groupby(level=0).apply(lambda g: g["a"].corr(g["b"], method="spearman")).dropna()
    yr = ic.groupby(ic.index.year).mean() * 100
    print(f"{nm} h={h}: " + "  ".join(f"{y}:{v:+.1f}" for y, v in yr.items()) + "  (x100)")
