"""Two follow-ups.

A. If cutting size after a volatility spike is what hurts (x15: fee-free cc60 1.485 vs
   rv3 1.172), then the profitable direction is not "be big when vol is high" -- that was
   flat in x14 -- but "be big when vol is RISING", i.e. when the trend is accelerating.
   mult = (vol20 / vol60) ^ theta, theta > 0.

B. The within-year funding tilt survived its own Simpson check (+0.045 Sharpe, both
   halves up) but is not significant.  tk30 died on the cross-asset test, so this one gets
   the same treatment: run the identical rule on ETH without refitting anything.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
import c1

pd.set_option("display.width", 240)
BPY = 365
EXPO = 0.45

# funding panel from the carry download, which covers both symbols
FC, _ = c1.load()


def prep(sym):
    C, O, H, L, F = lev.load_perp((sym,))
    c = C[sym]
    r = np.log(c).diff()
    vol60 = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
    vol20 = (r.rolling(20, min_periods=10).std() * np.sqrt(BPY)).clip(lower=0.15)
    vol5 = (r.rolling(5, min_periods=3).std() * np.sqrt(BPY)).clip(lower=0.15)
    fnd = FC[sym].reindex(c.index).fillna(0.0)
    fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)
    yr = fnd.index.year
    fq_yr = fnd.groupby(yr).expanding(min_periods=20).apply(
        lambda s: (s.iloc[-1] > s).mean()).reset_index(level=0, drop=True).reindex(fnd.index)
    fq_mix = fq_yr.where(fq_yr.notna() & (fnd.groupby(yr).cumcount() >= 20), fq).fillna(0.5)
    return dict(sym=sym, C=C, O=O, H=H, L=L, F=pd.DataFrame({sym: fnd}), c=c,
                vol60=vol60, vol20=vol20, vol5=vol5, z=lev.zscore(C)[sym],
                fq=fq, fq_mix=fq_mix)


def book(d, mult=None, match=True):
    tgt = (0.40 / d["vol60"]).clip(upper=1.0)
    if mult is not None:
        tgt = tgt * mult
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
                h1=sh(x.iloc[:h]), h2=sh(x.iloc[h:])), x


btc, eth = prep("BTCUSDT"), prep("ETHUSDT")

print("=== A. volatility acceleration tilt, BTC (exposure matched) ===")
print("mult = (vol20/vol60)^theta;  theta>0 = bigger while volatility is rising\n")
rows, ser = [], {}
for th in (-1.0, -0.5, 0.0, 0.25, 0.5, 0.75, 1.0):
    rel = (btc["vol20"] / btc["vol60"]).clip(0.4, 2.5)
    W, A = book(btc, mult=rel.pow(th))
    st, x = stats(btc, W, A, f"theta {th:+.2f}")
    rows.append(st); ser[f"{th:+.2f}"] = x
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n  year-by-year (%), the three contenders")
print(pd.DataFrame({k: v.groupby(v.index.year).apply(lambda s: (1 + s).prod() - 1) * 100
                    for k, v in [("theta 0", ser["+0.00"]), ("theta +0.50", ser["+0.50"]),
                                 ("theta -0.50", ser["-0.50"])]}).round(1).to_string())

print("\n=== B. funding tilt, identical rule on ETH (no refit) ===")
rows = []
for d in (btc, eth):
    for nm, f, th in [("none", btc["fq_mix"], 0.0),
                      ("within-yr -0.25", None, -0.25),
                      ("within-yr -0.50", None, -0.50)]:
        ff = d["fq_mix"] if f is None else f
        W, A = book(d, mult=(ff / 0.5).clip(0.2, 2.0).pow(th))
        rows.append(stats(d, W, A, f"{d['sym']} {nm}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== C. vol-acceleration on ETH, same rule ===")
rows = []
for d in (btc, eth):
    for th in (0.0, 0.5):
        rel = (d["vol20"] / d["vol60"]).clip(0.4, 2.5)
        W, A = book(d, mult=rel.pow(th))
        rows.append(stats(d, W, A, f"{d['sym']} theta {th:+.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))
