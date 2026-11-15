"""The short gate is a funding gate, and funding is the wrong gate in exactly one regime.

Funding is positive when longs are crowded, which is when a short is paid to wait.  That
is a good reason to short a market that is going up.  It is a bad reason to refuse to
short a market that is already going down: in 2022 funding went negative for months and
the gate closed, so the book sat out the one bear market it had.  Gate 0.20 recovered
+24pp in 2022 but gave some back in 2025, and the difference is inside its own noise.

So this tests an OR rather than a lower threshold: short if funding is rich OR the market
is in a confirmed downtrend.  One extra condition, motivated by the mechanism, not by the
backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
import c1

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"

C, O, H, L, F = lev.load_perp((S,))
c = C[S]
r = c.pct_change()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
px = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

ma200 = c.rolling(200, min_periods=100).mean()
below_ma = c < ma200
ma50 = c.rolling(50, min_periods=25).mean()

f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
dn = fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)


def book(gate, s_enter=0.20):
    tgt = (0.40 / vol).clip(upper=1.0)
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -s_enter) & gate.fillna(False), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    A = pd.Series(1.0, index=c.index)
    A = A.mask((vol < 0.60) & (px > -0.20), 1.25)
    A = A.mask((vol < 0.45) & (px > -0.10) & (z > 0.20), 1.75)
    return W, A


def run(W, A, label=""):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    gross = (W[S].abs() * A).shift(1).fillna(0.0)
    x = x + (((1.0 - gross).clip(lower=0.0) / 1.5) * dn).loc[x.index]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    n = len(x)
    cagr = (e.iloc[-1] ** (BPY / n) - 1) * 100
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:n // 2]), h2=sh(x.iloc[n // 2:]),
                days=int((W[S].loc["2020-06-01":] < -1e-9).sum())), x


print("=== 1. funding gate vs funding-or-downtrend ===")
rows, ser = [], {}
cands = {
    "funding > .40 (delivered)": (fq > 0.40),
    "funding > .20": (fq > 0.20),
    "funding > .40 or <MA200": (fq > 0.40) | below_ma,
    "funding > .40 or <MA50": (fq > 0.40) | (c < ma50),
    "funding > .40 or dd<-30%": (fq > 0.40) | (px < -0.30),
    "<MA200 only": below_ma,
    "no gate": pd.Series(True, index=c.index),
}
for nm, g in cands.items():
    st, x = run(*book(g), nm)
    rows.append(st); ser[nm] = x
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== 2. per-year (%) ===")
print(pd.DataFrame({k: v.groupby(v.index.year).apply(lambda s: (1 + s).prod() - 1) * 100
                    for k, v in ser.items()}).round(1).to_string())

print("\n=== 3. bootstrap vs delivered, and the trade count it adds ===")
base = ser["funding > .40 (delivered)"].to_numpy()
rng = np.random.default_rng(31)
blk, n = 20, 4000
for nm in ["funding > .40 or <MA200", "funding > .40 or <MA50",
           "funding > .40 or dd<-30%"]:
    b = ser[nm].to_numpy()
    m = min(len(base), len(b))
    st = rng.integers(0, m - blk, size=(n, m // blk))
    d = np.empty(n)
    for i in range(n):
        idx = (st[i][:, None] + np.arange(blk)).ravel()
        d[i] = (b[idx].mean() / b[idx].std() - base[idx].mean() / base[idx].std()) * np.sqrt(BPY)
    print(f"  {nm:28s} dSharpe {d.mean():+.3f}  90% [{np.percentile(d,5):+.3f},"
          f" {np.percentile(d,95):+.3f}]  P(d<=0) {(d<=0).mean():.3f}")
