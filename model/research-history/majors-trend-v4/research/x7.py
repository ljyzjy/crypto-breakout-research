"""Decide what survives. Paired bootstrap on both claims, then the final book."""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab
from x6 import book, C, O, dn

pd.set_option("display.width", 220)
BPY = 365
rng = np.random.default_rng(11)


def sh(x):
    return x.mean() / x.std() * np.sqrt(BPY)


def boot(a, b, n=4000):
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    av, bv = d["a"].to_numpy(), d["b"].to_numpy()
    obs = sh(pd.Series(av)) - sh(pd.Series(bv))
    k = len(av)
    ds = np.array([sh(pd.Series(av[i])) - sh(pd.Series(bv[i]))
                   for i in (rng.integers(0, k, k) for _ in range(n))])
    return obs, np.percentile(ds, 5), np.percentile(ds, 95), (ds <= 0).mean()


print("=== A. does portfolio-level vol targeting help or hurt? ===")
print("    (per-asset cap 1.0, no scaler  vs  scaler to 40% with 2.5x cap, same as x3)")
_, r_cap, _, _ = book(["BTCUSDT"], cap=1.0)
fwd = O.shift(-1) / O - 1
from x3 import core  # already vol-targeted inside bt()
from x3 import bt
_, r_scaled, _ = bt(core[["BTCUSDT"]], C, O)
o, lo, hi, p = boot(r_scaled, r_cap)
print(f"  scaled(40%,2.5x cap) Sharpe {sh(r_scaled):.3f}   plain {sh(r_cap):.3f}")
print(f"  dSharpe {o:+.3f}  90% CI [{lo:+.3f}, {hi:+.3f}]  P(d<=0) {p:.3f}")

print("\n=== B. carry sleeve: split-half and tails ===")
carry_all = (1 - book(["BTCUSDT"], cap=1.0)[2]).clip(lower=0) .shift(1).fillna(0) / 1.5 * dn
carry_all = carry_all.loc["2020-06-01":]
h = len(carry_all) // 2
for i, seg in enumerate((carry_all.iloc[:h], carry_all.iloc[h:])):
    print(f"  {'H1' if i == 0 else 'H2'}: ann {seg.mean() * BPY * 100:5.2f}%  vol {seg.std() * np.sqrt(BPY) * 100:4.2f}%  "
          f"Sharpe {sh(seg):5.2f}  worst day {seg.min() * 1e4:6.0f}bp")
c30 = carry_all.rolling(30).sum()
print(f"  worst rolling 30d: {c30.min() * 100:.2f}%   best {c30.max() * 100:.2f}%")
print(f"  carry notional avg {((1 - book(['BTCUSDT'], cap=1.0)[2]).clip(lower=0) / 1.5).loc['2020-06-01':].mean():.2f}")

print("\n=== C. combined, at three leverage levels ===")
_, r_trend, expo, w = book(["BTCUSDT"], cap=1.0)
idle = (1 - expo).clip(lower=0).shift(1).fillna(0)
carry = (idle / 1.5) * dn.reindex(idle.index)
rows = []
for lev in (1.0, 1.5, 2.0):
    for use_carry in (False, True):
        x = r_trend * lev + (carry * lev if use_carry else 0)
        x = x.dropna()
        eq = (1 + x).cumprod()
        yrs = len(x) / BPY
        mdd = (eq / eq.cummax() - 1).min()
        y = x.groupby(x.index.year).apply(lambda s: (1 + s).prod() - 1)
        rows.append(dict(lev=lev, carry=use_carry,
                         cagr=((eq.iloc[-1]) ** (1 / yrs) - 1) * 100,
                         vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                         mdd=mdd * 100, worst_m=-y.min() * 100,
                         y2022=y.get(2022, np.nan) * 100, y2026=y.get(2026, np.nan) * 100))
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== D. per-year return of the recommended config (1.5x + carry) ===")
x = (r_trend * 1.5 + carry * 1.5).dropna()
y = x.groupby(x.index.year).apply(lambda s: (1 + s).prod() - 1) * 100
b = r_trend.loc[x.index].groupby(r_trend.loc[x.index].year).apply(lambda s: (1 + s).prod() - 1) * 100
print("  trend 1.5x :  " + "  ".join(f"{i}:{v:6.1f}" for i, v in b.items()))
print("  +carry     :  " + "  ".join(f"{i}:{v:6.1f}" for i, v in y.items()))
