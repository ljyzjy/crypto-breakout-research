"""Every risk-control overlay has failed.  Time to test the opposite policy.

Five separate results point the same way:
  - the low-volatility tercile is the only losing one (-47%/yr);
  - faster vol estimates are monotonically worse, across three estimator families;
  - "cut leverage after a drawdown" made the drawdown deeper;
  - gating longs on rich funding destroyed the book (74.5% -> 1.8%);
  - the min(1, .) cap helps only because it refuses to up-size calm markets.

The common reading: this book earns its money in high-vol, crowded, trending conditions,
and every overlay that trims exactly those conditions is short the strategy's own edge.
If true, the correct policy is pro-cyclical: size UP when risk is high.

That is deliberately uncomfortable, so it gets the full battery: exposure matched, both
halves, every year, and the drawdown / Calmar visible next to the Sharpe.
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
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

vol_med = vol.rolling(365, min_periods=180).median()
vol_rel = (vol / vol_med).clip(0.3, 3.0)          # 1.0 = normal regime for this asset


def book(mult=None, gamma=1.0, cap=1.0, target_vol=0.40, match=True, label=""):
    """mult: multiplicative sizing tilt applied on top of the delivered formula."""
    raw = (target_vol / vol).pow(gamma).clip(upper=cap) if gamma > 0 else pd.Series(1.0, index=c.index)
    if mult is not None:
        raw = raw * mult
    lw = (z.clip(lower=0, upper=1.0) * raw).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * raw).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    if match:
        m = W[S].abs().loc["2020-06-01":].mean()
        if m > 1e-9:
            W = W * (EXPO / m)
    A = pd.Series(1.0, index=c.index)
    return W, A


def stats(W, A, label=""):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    h = len(x) // 2
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    cagr = (e.iloc[-1] ** (BPY / len(x)) - 1) * 100
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:h]), h2=sh(x.iloc[h:]), liq=m["liq"]), x


print("=== A. gamma sweep with the gamma=0 branch fixed ===")
rows = []
for g in (-0.50, -0.25, 0.0, 0.25, 0.50, 0.75, 1.00):
    W, A = book(gamma=g)
    rows.append(stats(W, A, f"gamma {g:+.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== B. pro-cyclical sizing: multiply by (vol / its 1y median) ^ theta ===")
print("theta>0 = bigger when volatility is high, theta<0 = the usual risk control\n")
rows = []
for th in (-0.50, -0.25, 0.0, 0.25, 0.50, 0.75, 1.00):
    W, A = book(mult=vol_rel.pow(th))
    rows.append(stats(W, A, f"vol tilt theta {th:+.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== C. funding tilt: multiply by (funding percentile / 0.5) ^ theta ===")
rows = []
for th in (-0.50, -0.25, 0.0, 0.25, 0.50):
    W, A = book(mult=(fq / 0.5).clip(0.2, 2.0).pow(th))
    rows.append(stats(W, A, f"fund tilt theta {th:+.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== D. the winner's year-by-year, if anything wins ===")
cands = {"delivered (gamma 1)": book()[0:2],
         "vol tilt +0.50": book(mult=vol_rel.pow(0.50)),
         "vol tilt +0.25": book(mult=vol_rel.pow(0.25)),
         "vol tilt -0.25": book(mult=vol_rel.pow(-0.25))}
ser = {}
for nm, (W, A) in cands.items():
    st, x = stats(W, A, nm)
    ser[nm] = x
print(pd.DataFrame({k: v.groupby(v.index.year).apply(
    lambda s: (1 + s).prod() - 1) * 100 for k, v in ser.items()}).round(1).to_string())
