"""Final consolidation.

The gate sweep showed a plateau from 0.20 to 0.60 and a cliff below 0.10, so the value
is in having a gate at all, not in its exact level.  Before touching a parameter that is
already in production, the difference between 0.20 and 0.40 has to clear the bootstrap --
moving a threshold inside its own noise band is how a backtest gets worse in real life.

Then the winning configuration gets the full book: spot base, carry on idle capital, and
the ladder, so the number quoted at the end is the same object that was delivered.
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
r = np.log(c).diff()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
dn = fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)


def book(sgate=0.40, band=0.0):
    tgt = (0.40 / vol).clip(upper=1.0)
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > sgate), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    if band > 0:
        held, out = 0.0, np.empty(len(W))
        for i, t in enumerate(W[S].to_numpy()):
            if abs(t - held) > band:
                held = t
            out[i] = held
        W = pd.DataFrame({S: out}, index=W.index)
    A = pd.Series(1.0, index=c.index)
    A = A.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
    A = A.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
    return W, A


def run(W, A, carry=True, label=""):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    if carry:
        gross = (W[S].abs() * A).shift(1).fillna(0.0)
        idle = (1.0 - gross).clip(lower=0.0)
        x = x + ((idle / 1.5) * dn).loc[x.index]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    n = len(x)
    cagr = (e.iloc[-1] ** (BPY / n) - 1) * 100
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:n // 2]), h2=sh(x.iloc[n // 2:]),
                l24=sh(x.iloc[-730:]), y25=x.loc["2025"].add(1).prod() * 100 - 100,
                y26=x.loc["2026"].add(1).prod() * 100 - 100), x


print("=== 1. gate 0.20 vs 0.40: is the difference real? ===")
_, x20 = run(*book(0.20), carry=False)
_, x40 = run(*book(0.40), carry=False)
a, b = x40.to_numpy(), x20.to_numpy()
rng = np.random.default_rng(23)
blk, n = 20, 4000
m = min(len(a), len(b))
st = rng.integers(0, m - blk, size=(n, m // blk))
d = np.empty(n)
for i in range(n):
    idx = (st[i][:, None] + np.arange(blk)).ravel()
    d[i] = (b[idx].mean() / b[idx].std() - a[idx].mean() / a[idx].std()) * np.sqrt(BPY)
print(f"  dSharpe (0.20 - 0.40) {d.mean():+.3f}  90% "
      f"[{np.percentile(d,5):+.3f}, {np.percentile(d,95):+.3f}]  P(d<=0) {(d<=0).mean():.3f}")
print("  -> moving the threshold is inside its own noise band" if (d <= 0).mean() > 0.10
      else "  -> the difference is significant")

print("\n=== 2. final book, every component on ===")
rows = []
for sg, bd, lbl in [(0.40, 0.00, "delivered (gate .40, no band)"),
                    (0.40, 0.10, "  + 10% no-trade band"),
                    (0.40, 0.05, "  + 5% band (the live file)"),
                    (0.20, 0.10, "gate .20 + 10% band")]:
    rows.append(run(*book(sg, bd), carry=True, label=lbl)[0])
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== 3. final book at three leverage settings ===")
W, A = book(0.40, 0.10)
rows = []
for mult in (1.0, 1.25, 1.5):
    rows.append(run(W, A * mult, carry=True, label=f"{mult}x")[0])
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== 4. per-year (%) at 1.0x, band 0.10 ===")
_, xf = run(W, A, carry=True)
print((xf.groupby(xf.index.year).apply(lambda s: (1 + s).prod() - 1) * 100).round(1).to_string())
print("\n  worst 90 days and the drawdown date:")
roll = xf.rolling(90).apply(lambda s: (1 + s).prod() - 1)
e = (1 + xf).cumprod()
print(f"    worst 90d {roll.min()*100:.1f}% ending {roll.idxmin().date()}")
print(f"    max drawdown {(e/e.cummax()-1).min()*100:.1f}% at {(e/e.cummax()-1).idxmin().date()}")
