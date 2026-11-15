"""Final ledger, delivered convention, everything on.

pct returns; base long in spot; carry on idle capital; ladder 1.0/1.25/1.75; funding gate
0.40; z cap 1.00; no-trade band 0.10 (the only change this round).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"

C, O, H, L, F = lev.load_perp((S,))
c = C[S]
r = c.pct_change()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
px = (c / c.rolling(365, min_periods=120).max() - 1.0)
fq = F[S].rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
dn = fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)


def book(band=0.0, sgate=0.40, zcap=1.0):
    tgt = (0.40 / vol).clip(upper=1.0)
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
    A = pd.Series(1.0, index=c.index)
    A = A.mask((vol < 0.60) & (px > -0.20), 1.25)
    A = A.mask((vol < 0.45) & (px > -0.10) & (z > 0.20), 1.75)
    return W, A


def run(W, A, label="", fee=lev.FEE):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True, fee=fee,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    gross = (W[S].abs() * A).shift(1).fillna(0.0)
    x = x + (((1.0 - gross).clip(lower=0.0) / 1.5) * dn).loc[x.index]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    n = len(x)
    cagr = (e.iloc[-1] ** (BPY / n) - 1) * 100
    roll = x.rolling(90).apply(lambda s: (1 + s).prod() - 1)
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:n // 2]), h2=sh(x.iloc[n // 2:]),
                l12=sh(x.iloc[-365:]), l24=sh(x.iloc[-730:]),
                w90=roll.min() * 100,
                turn=(W[S] * A).diff().abs().loc["2020-06-01":].sum() / (n / BPY),
                liq=m["liq"]), x


print("=== band choice on the real book ===")
rows = []
for bd in (0.0, 0.05, 0.10, 0.15):
    W, A = book(band=bd)
    rows.append(run(W, A, f"band {bd:.2f}")[0])
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== final ledger at three leverage settings (band 0.10) ===")
W, A = book(band=0.10)
rows, ser = [], {}
for mult in (1.0, 1.25, 1.5):
    st, x = run(W, A * mult, f"{mult:.2f}x")
    rows.append(st); ser[f"{mult:.2f}x"] = x
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== per-year (%) ===")
print(pd.DataFrame({k: v.groupby(v.index.year).apply(lambda s: (1 + s).prod() - 1) * 100
                    for k, v in ser.items()}).round(1).to_string())

print("\n=== 10bp cost stress ===")
rows = []
for mult in (1.0, 1.25, 1.5):
    rows.append(run(W, A * mult, f"{mult:.2f}x @10bp", fee=0.0010)[0])
print(pd.DataFrame(rows).round(2).to_string(index=False))
