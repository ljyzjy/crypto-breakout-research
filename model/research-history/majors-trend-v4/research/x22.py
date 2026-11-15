"""Reconcile the two baselines before quoting any number.

x10 reported 62.31% for the full book; x21 reports 60.96% for what should be the same
object.  A 1.35pp gap has to be explained, not averaged away, or every later comparison
inherits it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

BPY = 365
S = "BTCUSDT"
C, O, H, L, F = lev.load_perp((S,))
c = C[S]
z = lev.zscore(C)[S]
px = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
dn = fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)


def build(ret_kind):
    r = c.pct_change() if ret_kind == "pct" else np.log(c).diff()
    vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
    tgt = (0.40 / vol).clip(upper=1.0)
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    A = pd.Series(1.0, index=c.index)
    A = A.mask((vol < 0.60) & (px > -0.20), 1.25)
    A = A.mask((vol < 0.45) & (px > -0.10) & (z > 0.20), 1.75)
    return W, A, vol


def run(W, A, carry=True):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    if carry:
        gross = (W[S].abs() * A).shift(1).fillna(0.0)
        idle = (1.0 - gross).clip(lower=0.0)
        x = x + ((idle / 1.5) * dn).loc[x.index]
    e = (1 + x).cumprod()
    return dict(cagr=(e.iloc[-1] ** (BPY / len(x)) - 1) * 100,
                sharpe=x.mean() / x.std() * np.sqrt(BPY),
                mdd=(e / e.cummax() - 1).min() * 100,
                expo=(W[S].abs() * A).mean(),
                fund_pa=m["fund_pa"] * 100)


print("=== the same book built two ways ===")
for kind in ("pct", "log"):
    W, A, vol = build(kind)
    for ca in (False, True):
        d = run(W, A, carry=ca)
        print(f"  vol from {kind:3s} returns, carry={str(ca):5s}: "
              f"CAGR {d['cagr']:6.2f}%  S {d['sharpe']:.3f}  MDD {d['mdd']:6.2f}%  "
              f"expo {d['expo']:.3f}  funding {d['fund_pa']:.2f}%")

print("\n  vol series itself:")
_, _, vp = build("pct")
_, _, vl = build("log")
print(f"    mean {vp.mean()*100:.2f}% vs {vl.mean()*100:.2f}%   "
      f"max abs diff {(vp-vl).abs().max()*100:.2f}pp")
print(f"    ladder tier days: pct {(vp<0.45).sum()}/{((vp>=0.45)&(vp<0.60)).sum()}"
      f"   log {(vl<0.45).sum()}/{((vl>=0.45)&(vl<0.60)).sum()}")
