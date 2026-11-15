"""Re-verify the three conclusions under the delivered convention.

Everything from x11 onward used log returns for the volatility estimate; the shipped
strategy uses pct_change.  Within each script the comparison was apples to apples, so the
rankings should survive, but "should" is not "does".  This reruns the three decisions that
would actually change the strategy file, on pct returns, at matched exposure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"
EXPO = 0.445

C, O, H, L, F = lev.load_perp((S,))
c = C[S]
r = c.pct_change()                     # delivered convention
z = lev.zscore(C)[S]
px = (c / c.rolling(365, min_periods=120).max() - 1.0)
fq = F[S].rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
k = k.set_index("dt").sort_index()
lr = np.log(k["close"]).diff()
rv1 = (lr ** 2).groupby(lr.index.normalize()).sum().reindex(c.index)


def book(vol=None, zcap=1.0, band=0.0, sgate=0.40, match=True):
    v = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15) if vol is None else vol
    tgt = (0.40 / v).clip(upper=1.0)
    lw = (z.clip(lower=0, upper=zcap) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=zcap) * tgt).where((z < -0.20) & (fq > sgate), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    if band > 0:
        held, out = 0.0, np.empty(len(W))
        for i, t in enumerate(W[S].to_numpy()):
            if abs(t - held) > band:
                held = t
            out[i] = held
        W = pd.DataFrame({S: out}, index=W.index)
    if match:
        m = W[S].abs().loc["2020-06-01":].mean()
        W = W * (EXPO / m)
    A = pd.Series(1.0, index=c.index)
    A = A.mask((v < 0.60) & (px > -0.20), 1.25)
    A = A.mask((v < 0.45) & (px > -0.10) & (z > 0.20), 1.75)
    return W, A


def stats(W, A, label="", fee=lev.FEE):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True, fee=fee,
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
                turn=(W[S] * A).diff().abs().loc["2020-06-01":].sum() / (n / BPY)), x


print("=== 1. speed of the vol estimate (pct returns) ===")
rows = []
for nm, vv in [("cc20", (r.rolling(20, min_periods=10).std() * np.sqrt(BPY)).clip(lower=.15)),
               ("cc40", (r.rolling(40, min_periods=20).std() * np.sqrt(BPY)).clip(lower=.15)),
               ("cc60 (delivered)", None),
               ("cc120", (r.rolling(120, min_periods=60).std() * np.sqrt(BPY)).clip(lower=.15)),
               ("rv7", np.sqrt(rv1.rolling(7, min_periods=3).mean() * BPY).clip(lower=.15)),
               ("rv30", np.sqrt(rv1.rolling(30, min_periods=15).mean() * BPY).clip(lower=.15))]:
    W, A = book(vol=vv)
    rows.append(stats(W, A, nm)[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 2. no-trade band, at 4bp and at 10bp ===")
rows = []
for bd in (0.0, 0.05, 0.10, 0.15, 0.20):
    for fee in (0.0004, 0.0010):
        W, A = book(band=bd)
        rows.append(stats(W, A, f"band {bd:.2f} fee {fee*1e4:.0f}bp", fee=fee)[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 3. z weight cap ===")
rows = []
for zc in (0.75, 1.00, 1.50, 2.00):
    W, A = book(zcap=zc)
    rows.append(stats(W, A, f"z cap {zc:.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 4. what actually matters: the delivered book, exact ===")
W, A = book()
for lbl, bd in [("no band", 0.0), ("band 0.10", 0.10)]:
    Wb, Ab = book(band=bd)
    m = Wb[S].abs().loc["2020-06-01":].mean()
    # do not match here: quote the real book, and add carry on top
    st, x = stats(Wb, Ab, lbl)
    print(f"  {lbl:10s} CAGR {st['cagr']:6.2f}%  S {st['sharpe']:.3f}  "
          f"MDD {st['mdd']:6.2f}%  expo {m:.3f}  turnover {st['turn']:.1f}x/yr")
