"""The short leg is the weakest and most constrained part of the book.

The funding gate requires the funding rate to sit above the 40th percentile of its own
trailing year before a short is allowed.  That rule was worth a lot: the shorts it
blocked lost 59.2% cumulatively.  But 2022 -- the only losing year -- is exactly when
funding goes negative in a bear market, which is when the gate shuts.

So either the gate is right and 2022 is the price of it, or the gate is inverted in the
one regime that matters.  The test is a threshold sweep, and the tell is whether the
answer is a plateau or a knife edge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365

C, O, H, L, F = lev.load_perp(("BTCUSDT",))
S = "BTCUSDT"
c = C[S]
r = np.log(c).diff()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)


def book(sgate=0.40, s_enter=0.20, long_only=False):
    tgt = (0.40 / vol).clip(upper=1.0)
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    if long_only:
        sw = pd.Series(0.0, index=c.index)
    else:
        gate = fq.notna() if sgate is None else (fq > sgate)
        sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -s_enter) & gate, 0.0)
    return (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)


def stats(W, label=""):
    A = pd.Series(1.0, index=c.index)
    A = A.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
    A = A.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    n = len(x)
    cagr = (e.iloc[-1] ** (BPY / n) - 1) * 100
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:n // 2]), h2=sh(x.iloc[n // 2:]),
                short_days=int((W[S].loc["2020-06-01":] < -1e-9).sum())), x


print("=== 1. short gate threshold sweep ===")
rows, ser = [], {}
for g in (None, 0.00, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70):
    W = book(sgate=g)
    st, x = stats(W, f"gate {('none' if g is None else f'{g:.2f}')}")
    rows.append(st); ser[st["cfg"]] = x
Wlo = book(long_only=True)
st_lo, x_lo = stats(Wlo, "long only")
rows.append(st_lo); ser["long only"] = x_lo
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 2. per-year (%), gate sweep ===")
pick = ["long only", "gate none", "gate 0.20", "gate 0.40", "gate 0.60"]
print(pd.DataFrame({k: ser[k].groupby(ser[k].index.year).apply(
    lambda s: (1 + s).prod() - 1) * 100 for k in pick if k in ser}).round(1).to_string())

print("\n=== 3. what did the short leg itself earn, by year? ===")
# long-only vs full, difference is the short leg's contribution (net of interactions)
for g in (None, 0.20, 0.40, 0.60):
    nm = f"gate {('none' if g is None else f'{g:.2f}')}"
    d = ser[nm] - ser["long only"]
    by = d.groupby(d.index.year).apply(lambda s: s.sum() * 100)
    print(f"  {nm:10s} short-leg contribution by year (% of equity): "
          + "  ".join(f"{y}:{v:+.1f}" for y, v in by.items()))

print("\n=== 4. is the gate doing work in bear markets, or just cutting shorts? ===")
bear = (px_dd < -0.30)
for g in (None, 0.20, 0.40, 0.60):
    W = book(sgate=g)
    sd = (W[S] < -1e-9)
    print(f"  gate {('none' if g is None else f'{g:.2f}'):6s}: short days {int(sd.sum()):4d}"
          f"   of which in >30% drawdown {int((sd & bear).sum()):4d}"
          f"   ({int((sd & bear).sum()) / max(int(sd.sum()), 1) * 100:.0f}%)")
