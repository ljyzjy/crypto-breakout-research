"""The denominator, part 3: is it speed, or is it how hard you scale?

A slow vol estimate has little time variation, so 0.4/vol_slow is nearly a constant, so
"slow is better" and "less volatility targeting is better" predict the same thing.  They
are not the same policy though: one says keep the target but measure risk lazily, the
other says keep the measurement and shrink the response.

Separate them with scale = min(cap, (target/vol)^gamma):
    gamma = 0    no risk scaling at all, pure z weight
    gamma = 1    exact volatility targeting (the delivered policy)
Every run is rescaled to the same average exposure, so gamma only changes WHEN you are
big, never HOW big on average.  Without that, gamma is indistinguishable from leverage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"
EXPO = 0.45

C, O, H, L, F = lev.load_perp((S,))
c = C[S]
r = np.log(c).diff()

k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
k = k.set_index("dt").sort_index()
lr = np.log(k["close"]).diff()
rv1 = (lr ** 2).groupby(lr.index.normalize()).sum().reindex(c.index)

z = lev.zscore(C)[S]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fq = F[S].rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)


def vol_cc(n):
    return (r.rolling(n, min_periods=max(10, n // 2)).std() * np.sqrt(BPY)).clip(lower=0.15)


def book(vol, gamma=1.0, cap=1.0, target_vol=0.40, ladder=False, match=True):
    raw = (target_vol / vol).clip(upper=cap) if gamma == 0 else \
        (target_vol / vol).pow(gamma).clip(upper=cap)
    lw = (z.clip(lower=0, upper=1.0) * raw).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * raw).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    A = pd.Series(1.0, index=c.index)
    if ladder:
        A = A.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
        A = A.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
    if match:
        m = (W[S].abs() * A).loc["2020-06-01":].mean()
        W = W * (EXPO / m)
    return W, A


def stats(W, A, label=""):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    h = len(x) // 2
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    return dict(cfg=label,
                cagr=(e.iloc[-1] ** (BPY / len(x)) - 1) * 100,
                vol=x.std() * np.sqrt(BPY) * 100,
                sharpe=sh(x), mdd=dd.min() * 100,
                calmar=(e.iloc[-1] ** (BPY / len(x)) - 1) / abs(dd.min()),
                h1=sh(x.iloc[:h]), h2=sh(x.iloc[h:]), liq=m["liq"]), x


print("=== A. gamma (how hard you scale) x speed (how fast you measure) ===")
print("all rows rescaled to the same average exposure 0.45; only timing differs\n")
rows = []
for n in (20, 40, 60, 120):
    for g in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25):
        W, A = book(vol_cc(n), gamma=g)
        rows.append(stats(W, A, f"cc{n:3d} g={g:.2f}")[0])
t = pd.DataFrame(rows)
piv = t.pivot_table(index="cfg", values="sharpe")
print(t.round(3).to_string(index=False))

print("\n  Sharpe grid (rows = window, cols = gamma)")
grid = pd.DataFrame(index=[20, 40, 60, 120], columns=[0.0, 0.25, 0.5, 0.75, 1.0, 1.25],
                    dtype=float)
for _, row in t.iterrows():
    n = int(row.cfg.split()[0][2:])
    g = float(row.cfg.split("g=")[1])
    grid.loc[n, g] = row.sharpe
print(grid.round(3).to_string())

print("\n=== B. same grid, but with NO cap (cap=3) -- does the cap do the work? ===")
rows = []
for n in (20, 60, 120):
    for g in (0.5, 1.0):
        W, A = book(vol_cc(n), gamma=g, cap=3.0)
        rows.append(stats(W, A, f"cc{n:3d} g={g:.2f} cap=3")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== C. cap sweep at the delivered speed and gamma ===")
rows = []
for cap in (0.75, 1.0, 1.25, 1.5, 2.0):
    W, A = book(vol_cc(60), gamma=1.0, cap=cap)
    rows.append(stats(W, A, f"cc60 g=1 cap={cap}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== D. per-year Sharpe of the finalists ===")
fin = {}
for n, g in [(60, 1.0), (60, 0.5), (60, 0.75), (20, 1.0), (120, 1.0)]:
    W, A = book(vol_cc(n), gamma=g)
    st, x = stats(W, A, f"cc{n} g={g}")
    fin[f"cc{n}g{g}"] = x
print(pd.DataFrame({k: v.groupby(v.index.year).apply(
    lambda s: s.mean() / s.std() * np.sqrt(BPY)) for k, v in fin.items()}).round(2).to_string())
