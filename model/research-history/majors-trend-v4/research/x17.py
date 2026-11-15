"""Does volatility acceleration actually predict, or is it only a reshuffled denominator?

A sizing tilt that helps in a backtest can be three different things:
  (i)  a real conditional effect -- the book earns more per unit of exposure when the
       ratio is high, and a bucket table shows it directly;
  (ii) an artifact of interacting with the cap and the exposure matching;
  (iii) a directional signal in disguise, in which case it belongs in the signal layer
       and has to survive the AUC screen like everything else.

All three get tested, on BTC and on ETH.
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
    vol60 = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
    vol20 = (r.rolling(20, min_periods=10).std() * np.sqrt(BPY)).clip(lower=0.15)
    fnd = FC[sym].reindex(c.index).fillna(0.0)
    fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)
    return dict(sym=sym, C=C, O=O, H=H, L=L, F=pd.DataFrame({sym: fnd}), c=c,
                vol60=vol60, vol20=vol20, z=lev.zscore(C)[sym], fq=fq)


def book(d, theta=0.0, gamma=1.0, match=True):
    tgt = (0.40 / d["vol60"]).pow(gamma).clip(upper=1.0)
    if theta:
        tgt = tgt * (d["vol20"] / d["vol60"]).clip(0.4, 2.5).pow(theta)
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
    h = len(x) // 2
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    cagr = (e.iloc[-1] ** (BPY / len(x)) - 1) * 100
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:h]), h2=sh(x.iloc[h:]), liq=m["liq"]), x


btc, eth = prep("BTCUSDT"), prep("ETHUSDT")


def bucket(d, ret, name):
    """daily P&L per unit of realised exposure, by vol20/vol60 quintile"""
    expo = (book(d, theta=0.0)[0][d["sym"]].abs() * 1.0).shift(1).fillna(0.0)
    rel = (d["vol20"] / d["vol60"]).reindex(ret.index)
    m = ret.index
    t = pd.DataFrame({"rel": rel.reindex(m), "r": ret, "e": expo.reindex(m)}).dropna()
    t = t[t.e > 0.05]
    t["unit"] = t.r / t.e
    t["b"] = pd.qcut(t.rel, 5, labels=False, duplicates="drop")
    g = t.groupby("b").agg(n=("unit", "size"), rel_lo=("rel", "min"), rel_hi=("rel", "max"),
                           rel_med=("rel", "median"),
                           unit_bp=("unit", lambda s: s.mean() * 1e4),
                           win=("unit", lambda s: (s > 0).mean() * 100),
                           shp=("unit", lambda s: s.mean() / s.std() * np.sqrt(BPY)))
    print(f"\n  [{name}] daily return per unit exposure, by vol20/vol60 quintile")
    print(g.round(3).to_string())


print("=== 1. bucket table: does the book earn more when vol is accelerating? ===")
W0, A0 = book(btc)
_, r0 = stats(btc, W0, A0, "btc base")
bucket(btc, r0, "BTC, delivered sizing")
W1, A1 = book(eth)
_, r1 = stats(eth, W1, A1, "eth base")
bucket(eth, r1, "ETH, delivered sizing")

print("\n=== 2. is it a directional signal? forward returns by the same quintile ===")
for d in (btc, eth):
    rel = (d["vol20"] / d["vol60"]).clip(0.4, 2.5)
    out = []
    for h in (5, 20, 60):
        fwd = d["c"].shift(-h) / d["c"] - 1
        t = pd.DataFrame({"rel": rel, "f": fwd}).dropna()
        t["b"] = pd.qcut(t.rel, 5, labels=False, duplicates="drop")
        g = t.groupby("b")["f"].mean() * 100
        out.append(g.rename(f"{h}d %"))
    print(f"\n  {d['sym']}: mean forward return (%) by vol-acceleration quintile")
    print(pd.concat(out, axis=1).round(2).to_string())

print("\n=== 3. theta beyond 1.0, and the interaction with gamma ===")
rows = []
for g in (0.5, 1.0):
    for th in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        W, A = book(btc, theta=th, gamma=g)
        rows.append(stats(btc, W, A, f"gamma {g} theta {th:+.1f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 4. the chosen one: halves and bootstrap ===")
ser = {}
for th in (0.0, 1.0, 1.5):
    W, A = book(btc, theta=th)
    st, x = stats(btc, W, A, f"theta {th}")
    ser[th] = x
base = ser[0.0].to_numpy()
rng = np.random.default_rng(11)


def boot(a, b, n=3000, blk=20):
    m = min(len(a), len(b))
    a, b = a[-m:], b[-m:]
    nb = m // blk
    st = rng.integers(0, m - blk, size=(n, nb))
    out = np.empty(n)
    for i in range(n):
        idx = (st[i][:, None] + np.arange(blk)).ravel()
        sa = b[idx].mean() / b[idx].std() * np.sqrt(BPY)
        sb = a[idx].mean() / a[idx].std() * np.sqrt(BPY)
        out[i] = sa - sb
    return out


for th in (1.0, 1.5):
    dd = boot(base, ser[th].to_numpy())
    print(f"  theta {th:.1f}: dSharpe {dd.mean():+.3f}  "
          f"90% [{np.percentile(dd,5):+.3f}, {np.percentile(dd,95):+.3f}]  "
          f"P(d<=0) {(dd<=0).mean():.3f}")

print("\n=== 5. per-year, theta 0 / 1.0 / 1.5 ===")
print(pd.DataFrame({f"theta {k}": v.groupby(v.index.year).apply(
    lambda s: (1 + s).prod() - 1) * 100 for k, v in ser.items()}).round(1).to_string())
