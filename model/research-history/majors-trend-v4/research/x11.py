"""Is the denominator of the position size estimated well?

w = z * min(1, 0.40 / vol).  Everything rides on `vol`.  The delivered version uses
60 daily close-to-close returns, which throws away the open, the high and the low of
every day and every hourly print.  Range-based and intraday realized estimators are
5-10x more efficient at the same sample length (Parkinson 1980, Garman-Klass 1980,
Andersen-Bollerslev 1998).  A better denominator is not a new signal -- it is a better
measurement of a quantity we already trade on -- so it cannot decay the way a signal does.

Part 1: forecast accuracy for the next 5 days of realized variance.
Part 2: what each estimator does to the P&L, at matched average exposure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"

C, O, H, L, F = lev.load_perp((S,))
c, o, h, l = C[S], O[S], H[S], L[S]
r = np.log(c).diff()

# ---------------------------------------------------------------- estimators
# every column is an annualized volatility known at the close of that day
V = pd.DataFrame(index=c.index)

for n in (10, 20, 40, 60, 120):
    V[f"cc{n}"] = r.rolling(n, min_periods=max(10, n // 2)).std() * np.sqrt(BPY)

for hl in (5, 10, 20):
    V[f"ewma{hl}"] = np.sqrt((r ** 2).ewm(halflife=hl, min_periods=10).mean() * BPY)

# Parkinson: uses only the range, 4 ln2 is the variance of a Brownian range
hl_ = np.log(h / l) ** 2 / (4 * np.log(2))
for n in (10, 20, 60):
    V[f"park{n}"] = np.sqrt(hl_.rolling(n, min_periods=max(5, n // 2)).mean() * BPY)

# Garman-Klass: range plus the open-close body
gk_ = 0.5 * np.log(h / l) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
for n in (10, 20, 60):
    V[f"gk{n}"] = np.sqrt(gk_.clip(lower=0).rolling(n, min_periods=max(5, n // 2)).mean() * BPY)

# Rogers-Satchell: drift independent, so it does not mistake a trend for volatility
rs_ = (np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o))
for n in (20,):
    V[f"rs{n}"] = np.sqrt(rs_.clip(lower=0).rolling(n, min_periods=10).mean() * BPY)

# realised variance straight from the hourly bars
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
k = k.set_index("dt").sort_index()
lr = np.log(k["close"]).diff()
rv1 = (lr ** 2).groupby(lr.index.normalize()).sum().reindex(c.index)
for n in (7, 14, 30):
    V[f"rv1h{n}"] = np.sqrt(rv1.rolling(n, min_periods=max(3, n // 2)).mean() * BPY)

# HAR: daily + weekly + monthly RV, the standard cascade
V["har"] = np.sqrt((0.4 * rv1 + 0.3 * rv1.rolling(5).mean()
                    + 0.3 * rv1.rolling(22).mean()) * BPY)

# average of three independent estimators -- errors are not perfectly correlated
V["blend"] = V[["cc20", "park20", "rv1h14"]].mean(axis=1)

V = V.clip(lower=0.15)

# ---------------------------------------------------------------- 1. accuracy
# target: realised annualized variance over the NEXT 5 trading days, from hourly data.
# Using hourly RV as truth also keeps the target from favouring any daily estimator.
fwd_var = rv1.rolling(5).sum().shift(-5) / 5 * BPY

rows = []
for col in V.columns:
    fv = (V[col] ** 2)
    m = fv.notna() & fwd_var.notna() & (fwd_var > 0) & (fv > 0)
    f, a = fv[m], fwd_var[m]
    rat = a / f
    rows.append(dict(est=col,
                     qlike=(rat - np.log(rat) - 1).mean(),
                     mse_log=((np.log(f) - np.log(a)) ** 2).mean(),
                     bias=(f.mean() / a.mean() - 1) * 100,
                     corr=f.corr(a),
                     ann=f.mean() ** 0.5 * 100, n=int(m.sum())))
acc = pd.DataFrame(rows).sort_values("qlike")

print("=== 1. which estimator forecasts the next 5 days best? ===")
print("qlike and mse_log: lower is better. bias: +ve = over-forecasts. "
      "corr: on variance levels.")
print(acc.round(5).to_string(index=False))

# rank stability across the two halves
print("\n  qlike by half (lower is better):")
h1 = fwd_var.index < fwd_var.index[len(fwd_var) // 2]
for col in acc["est"].head(8):
    fv = V[col] ** 2
    out = []
    for msk in (h1, ~h1):
        m = fv.notna() & fwd_var.notna() & (fwd_var > 0) & (fv > 0) & msk
        rat = fwd_var[m] / fv[m]
        out.append((rat - np.log(rat) - 1).mean())
    print(f"    {col:9s} H1 {out[0]:.5f}   H2 {out[1]:.5f}")

# ---------------------------------------------------------------- 2. the P&L
z = lev.zscore(C)[S]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)


def book(vol, ladder=True, target_vol=0.40, band=0.0):
    tgt = (target_vol / vol).clip(upper=1.0)
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    A = pd.Series(1.0, index=c.index)
    if ladder:
        A = A.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
        A = A.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
        A = A.clip(1.0, 3.0)
    return W, A


def stats(W, A, label=""):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                  start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    yrs = len(x) / BPY
    return dict(cfg=label,
                cagr=(e.iloc[-1] ** (1 / yrs) - 1) * 100,
                vol=x.std() * np.sqrt(BPY) * 100,
                sharpe=x.mean() / x.std() * np.sqrt(BPY),
                mdd=dd.min() * 100,
                calmar=(e.iloc[-1] ** (1 / yrs) - 1) / abs(dd.min()),
                expo=(W[S].abs() * A).mean())


print("\n=== 2. strategy P&L by estimator (ladder on, target 40%) ===")
rows = []
for col in ["cc60", "cc20", "ewma10", "park20", "gk20", "rs20", "rv1h7", "rv1h14",
            "rv1h30", "har", "blend"]:
    W, A = book(V[col])
    rows.append(stats(W, A, col))
tab = pd.DataFrame(rows)
print(tab.round(3).to_string(index=False))

print("\n  same, but scaled to identical average exposure (isolates size from risk):")
rows2 = []
for col in ["cc60", "cc20", "ewma10", "park20", "gk20", "rs20", "rv1h7", "rv1h14",
            "rv1h30", "har", "blend"]:
    W, A = book(V[col])
    base = (W[S].abs() * A).mean()
    sc = tab.loc[tab.cfg == col, "expo"].iloc[0] / base
    W2, A2 = W * sc, A
    rows2.append(stats(W2, A2, col))
print(pd.DataFrame(rows2).round(3).to_string(index=False))

print("\n=== 3. how much does vol targeting contribute at all? (fixed weight = z) ===")
rows = []
for col, lbl in [("cc60", "vol-target cc60 (baseline)"), ("blend", "vol-target blend")]:
    W, A = book(V[col])
    rows.append(stats(W, A, lbl))
# no vol scaling: weight = z, but then exposure is far higher; match it instead
for tgtv, lbl in [(0.40, "fixed 40% notional, no vol scaling")]:
    tgt = pd.Series(tgtv, index=c.index)
    W, A = book(tgt)
    rows.append(stats(W, A, lbl))
print(pd.DataFrame(rows).round(3).to_string(index=False))
