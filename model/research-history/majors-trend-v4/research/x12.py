"""The denominator, part 2.

x11 found something backwards: the estimator with the best forecast (EWMA10, qlike 0.323)
produces the worst book, and the crude 60-day close-to-close one produces the best.  Two
possible reasons, and they call for different actions:

  a) the comparison was confounded by exposure -- several estimators imply different
     average size, and Sharpe is not scale free once the min(1, .) cap binds;
  b) the strategy genuinely wants a SLOW vol estimate.  Trend following earns its money
     when volatility is high, so an estimator that cuts size the moment vol spikes cuts
     exactly where the returns are.  Slowness is then a feature, not a defect.

This separates the two: fix average exposure at one number, then sweep the horizon.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"
TARGET_EXPO = 0.45          # common notional/equity for every comparison

C, O, H, L, F = lev.load_perp((S,))
c, o, h, l = C[S], O[S], H[S], L[S]
r = np.log(c).diff()

k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
k = k.set_index("dt").sort_index()
lr = np.log(k["close"]).diff()
rv1 = (lr ** 2).groupby(lr.index.normalize()).sum().reindex(c.index)

z = lev.zscore(C)[S]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

hl_ = np.log(h / l) ** 2 / (4 * np.log(2))
gk_ = (0.5 * np.log(h / l) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2).clip(lower=0)


def est(kind, n, hl=None):
    if kind == "cc":
        return r.rolling(n, min_periods=max(10, n // 2)).std() * np.sqrt(BPY)
    if kind == "ewma":
        return np.sqrt((r ** 2).ewm(halflife=n, min_periods=10).mean() * BPY)
    if kind == "park":
        return np.sqrt(hl_.rolling(n, min_periods=max(5, n // 2)).mean() * BPY)
    if kind == "gk":
        return np.sqrt(gk_.rolling(n, min_periods=max(5, n // 2)).mean() * BPY)
    if kind == "rv":
        return np.sqrt(rv1.rolling(n, min_periods=max(3, n // 2)).mean() * BPY)
    raise ValueError(kind)


def book(vol, ladder=False, target_vol=0.40, match=True):
    tgt = (target_vol / vol.clip(lower=0.15)).clip(upper=1.0)
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    A = pd.Series(1.0, index=c.index)
    if ladder:
        A = A.mask((vol.clip(lower=0.15) < 0.60) & (px_dd > -0.20), 1.25)
        A = A.mask((vol.clip(lower=0.15) < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
    if match:
        m = (W[S].abs() * A).loc["2020-06-01":].mean()
        if m > 1e-9:
            W = W * (TARGET_EXPO / m)
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
                h1=sh(x.iloc[:h]), h2=sh(x.iloc[h:]),
                expo=(W[S].abs() * A).mean()), x


print("=== A. same average exposure (0.45), ladder off ===")
rows, ser = [], {}
cand = [("cc", 20), ("cc", 60), ("cc", 120), ("cc", 250),
        ("ewma", 5), ("ewma", 20), ("ewma", 60), ("ewma", 120),
        ("park", 20), ("gk", 20), ("rv", 7), ("rv", 30)]
for kind, n in cand:
    vol = est(kind, n)
    W, A = book(vol)
    st, x = stats(W, A, f"{kind}{n}")
    rows.append(st); ser[f"{kind}{n}"] = x
t = pd.DataFrame(rows)
print(t.round(3).to_string(index=False))
print(f"\n  rank by Sharpe: {', '.join(t.sort_values('sharpe', ascending=False).cfg.head(5))}")

print("\n=== B. slowness sweep, exposure matched ===")
print("  close-to-close window")
rows = []
for n in (10, 20, 30, 40, 60, 80, 100, 120, 160, 200, 250):
    W, A = book(est("cc", n))
    rows.append(stats(W, A, f"cc{n}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))
print("\n  EWMA half-life")
rows = []
for n in (3, 5, 10, 20, 40, 60, 90, 120):
    W, A = book(est("ewma", n))
    rows.append(stats(W, A, f"ewma{n}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))
print("\n  realised variance from hourly bars")
rows = []
for n in (3, 7, 14, 30, 60, 120):
    W, A = book(est("rv", n))
    rows.append(stats(W, A, f"rv{n}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== C. per-year Sharpe, cc60 vs the two extremes ===")
pick = ["cc20", "cc60", "cc120", "ewma10", "rv30"]
yrs = pd.DataFrame({nm: ser[nm].groupby(ser[nm].index.year).apply(
    lambda s: s.mean() / s.std() * np.sqrt(BPY)) for nm in pick if nm in ser})
print(yrs.round(2).to_string())

print("\n=== D. does the ladder still help with each estimator? ===")
rows = []
for kind, n in [("cc", 60), ("cc", 120), ("ewma", 60), ("rv", 30)]:
    vol = est(kind, n)
    for lad in (False, True):
        W, A = book(vol, ladder=lad)
        rows.append(stats(W, A, f"{kind}{n} ladder={lad}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))
