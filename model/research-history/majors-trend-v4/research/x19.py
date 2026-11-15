"""Two things that cost nothing to change and are not predictions.

1. Turnover.  The research engine rebalances to the exact target every single day; the
   delivered strategy file has a 5% no-trade band.  Those are different books, and the
   one that was measured is the more expensive one: 34x/year of notional at 8bp round
   trip is 2.76%/yr.  A band is not a forecast, it is plumbing -- it cannot decay.

2. The z cap.  Weight is min(z, 1.0) * scale, so z = 1, 2 and 3 all get the same size,
   even though the bucket work showed the payoff ratio rising with |z| (0.99 -> 1.38)
   while the win rate stayed flat.  All the information is in the payoff, and the cap
   throws away everything above z = 1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
EXPO = 0.45

C, O, H, L, F = lev.load_perp(("BTCUSDT",))
S = "BTCUSDT"
c = C[S]
r = np.log(c).diff()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)


def target(zcap=1.0, mult=None):
    tgt = (0.40 / vol).clip(upper=1.0)
    if mult is not None:
        tgt = tgt * mult
    lw = (z.clip(lower=0, upper=zcap) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=zcap) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
    return (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)


def with_band(W, band):
    """no-trade band on notional/equity: only move if the target is further than `band`"""
    if band <= 0:
        return W
    out = W.copy()
    held = 0.0
    vals = W[S].to_numpy()
    res = np.empty_like(vals)
    for i, tgt in enumerate(vals):
        if abs(tgt - held) > band:
            held = tgt
        res[i] = held
    out[S] = res
    return out


def stats(W, A, label="", fee=lev.FEE):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True, fee=fee,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    cagr = (e.iloc[-1] ** (BPY / len(x)) - 1) * 100
    turn = (W[S] * A).diff().abs().loc["2020-06-01":].sum() / (len(x) / BPY)
    n = len(x)
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:n // 2]), h2=sh(x.iloc[n // 2:]),
                turn=turn, cost=turn * fee * 2 * 100), x


print("=== 1. no-trade band, exact same signal, exposure matched AFTER banding ===")
rows = []
for band in (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30):
    W = with_band(target(), band)
    m = W[S].abs().loc["2020-06-01":].mean()
    rows.append(stats(W * (EXPO / m), pd.Series(1.0, index=c.index), f"band {band:.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 2. the same, at zero fees, to separate timing loss from cost saved ===")
rows = []
for band in (0.0, 0.05, 0.10, 0.20):
    W = with_band(target(), band)
    m = W[S].abs().loc["2020-06-01":].mean()
    rows.append(stats(W * (EXPO / m), pd.Series(1.0, index=c.index),
                      f"band {band:.2f} fee=0", fee=0.0)[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 3. z weight cap ===")
rows = []
for zc in (0.50, 0.75, 1.00, 1.50, 2.00, 3.00):
    W = target(zcap=zc)
    m = W[S].abs().loc["2020-06-01":].mean()
    rows.append(stats(W * (EXPO / m), pd.Series(1.0, index=c.index), f"z cap {zc:.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 4. best band x best z cap, with 10bp fees as a stress ===")
rows = []
for zc in (1.0, 1.5, 2.0):
    for band in (0.0, 0.10, 0.20):
        W = with_band(target(zcap=zc), band)
        m = W[S].abs().loc["2020-06-01":].mean()
        W = W * (EXPO / m)
        for fee in (0.0004, 0.0010):
            rows.append(stats(W, pd.Series(1.0, index=c.index),
                              f"zcap {zc} band {band} fee {fee*1e4:.0f}bp", fee=fee)[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))
