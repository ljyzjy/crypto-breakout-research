"""Is the "volatility collapse" regime a rule, or two bad episodes wearing a rule's clothes?

BTC bucket 0 (vol20/vol60 ~ 0.66) loses 13.4 bp/day per unit exposure, which annualises
to roughly -40%.  That is either a structural regime -- volatility collapsing means the
trend has died and the book should not be at maximum size -- or it is a handful of
specific months.  The distinction decides whether it is tradeable.

Three tests: how the loss is spread over time, whether it shows up in four independent
sub-periods, and whether a parameter-free version of the same idea does the same job.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
import c1

pd.set_option("display.width", 240)
BPY = 365
EXPO = 0.45
FC, _ = c1.load()


def prep(sym):
    C, O, H, L, F = lev.load_perp((sym,))
    c = C[sym]
    r = np.log(c).diff()
    v60 = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
    v20 = (r.rolling(20, min_periods=10).std() * np.sqrt(BPY)).clip(lower=0.15)
    fnd = FC[sym].reindex(c.index).fillna(0.0)
    fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)
    return dict(sym=sym, C=C, O=O, H=H, L=L, F=pd.DataFrame({sym: fnd}), c=c,
                v60=v60, v20=v20, z=lev.zscore(C)[sym], fq=fq)


def book(d, vol=None, theta=0.0, match=True):
    v = d["v60"] if vol is None else vol
    tgt = (0.40 / v).clip(upper=1.0)
    if theta:
        tgt = tgt * (d["v20"] / d["v60"]).clip(0.4, 2.5).pow(theta)
    z = d["z"]
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (d["fq"] > 0.40), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(d["sym"])
    if match:
        m = W[d["sym"]].abs().loc["2020-06-01":].mean()
        W = W * (EXPO / m)
    return W, pd.Series(1.0, index=d["c"].index)


def stats(d, W, A, label=""):
    m, eq, ret, liq = lev.simulate(W, A, d["C"], d["O"], d["H"], d["L"], funding=d["F"],
                                   liq=True, start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    cagr = (e.iloc[-1] ** (BPY / len(x)) - 1) * 100
    n = len(x)
    sh4 = [sh(x.iloc[i * n // 4:(i + 1) * n // 4]) for i in range(4)]
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                q1=sh4[0], q2=sh4[1], q3=sh4[2], q4=sh4[3]), x


btc, eth = prep("BTCUSDT"), prep("ETHUSDT")
W0, A0 = book(btc)
_, r0 = stats(btc, W0, A0)

print("=== 1. where does the bucket-0 loss actually sit? ===")
rel = (btc["v20"] / btc["v60"]).reindex(r0.index)
expo = (book(btc)[0]["BTCUSDT"].abs()).shift(1).reindex(r0.index).fillna(0.0)
t = pd.DataFrame({"rel": rel, "r": r0, "e": expo}).dropna()
t = t[t.e > 0.05]
t["unit"] = t.r / t.e
q0 = t[t.rel < t.rel.quantile(0.20)]
print(f"  bucket 0: n={len(q0)} days, total per-unit P&L {q0.unit.sum()*100:.1f}%")
by_y = q0.groupby(q0.index.year).agg(days=("unit", "size"), pnl=("unit", lambda s: s.sum() * 100))
print(by_y.round(1).to_string())
neg = q0.unit[q0.unit < 0]
print(f"  worst 10 days account for {neg.nsmallest(10).sum() / q0.unit.sum() * 100:.0f}% of the loss")
print(f"  distinct months touched: {q0.index.to_period('M').nunique()}")

print("\n  same on ETH for contrast:")
We, Ae = book(eth)
_, re_ = stats(eth, We, Ae)
rele = (eth["v20"] / eth["v60"]).reindex(re_.index)
expe = (book(eth)[0]["ETHUSDT"].abs()).shift(1).reindex(re_.index).fillna(0.0)
te = pd.DataFrame({"rel": rele, "r": re_, "e": expe}).dropna()
te = te[te.e > 0.05]
te["unit"] = te.r / te.e
q0e = te[te.rel < te.rel.quantile(0.20)]
print(f"  ETH bucket 0: n={len(q0e)}, total per-unit {q0e.unit.sum()*100:+.1f}%")
print(q0e.groupby(q0e.index.year).agg(days=("unit", "size"),
                                      pnl=("unit", lambda s: s.sum() * 100)).round(1).to_string())

print("\n=== 2. four independent sub-periods (Sharpe) ===")
rows = []
for th in (0.0, 0.5, 1.0, 1.5):
    W, A = book(btc, theta=th)
    rows.append(stats(btc, W, A, f"theta {th:.1f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 3. parameter-free forms of the same idea ===")
rows = []
forms = {
    "vol60 (delivered)": None,
    "min(v20,v60)": np.minimum(btc["v20"], btc["v60"]),
    "max(v20,v60)": np.maximum(btc["v20"], btc["v60"]),
    "sqrt(v20*v60)": np.sqrt(btc["v20"] * btc["v60"]),
    "mean(v20,v60)": (btc["v20"] + btc["v60"]) / 2,
}
for nm, vv in forms.items():
    W, A = book(btc, vol=vv)
    rows.append(stats(btc, W, A, nm)[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 4. the same forms on ETH, for the cross-asset check ===")
rows = []
for nm, f in [("vol60 (delivered)", lambda d: d["v60"]),
              ("max(v20,v60)", lambda d: np.maximum(d["v20"], d["v60"])),
              ("sqrt(v20*v60)", lambda d: np.sqrt(d["v20"] * d["v60"]))]:
    for d in (btc, eth):
        W, A = book(d, vol=f(d))
        rows.append(stats(d, W, A, f"{d['sym'][:3]} {nm}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))
