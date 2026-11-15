"""Two loose ends, both of which have burned this project before.

1. Is "fast vol estimates are worse" a cost effect or a timing effect?  With fee=0 the
   answer is unambiguous: cost cannot explain a Sharpe drop from 1.45 to 1.12 unless
   turnover differs by an order of magnitude.

2. The funding tilt (+0.09 Sharpe) has the exact shape of the oi_pct trap: good in the
   first half, worse in the second, driven by a variable that is highly persistent and
   therefore close to a proxy for "which year is it".  oi_pct passed every test until the
   percentile was recomputed inside each year, at which point it flipped sign.

Both get the same treatment: causal within-year percentile, half-splits, per-year, and a
paired block bootstrap.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"
EXPO = 0.45

C, O, H, L, F = lev.load_perp((S,))
c = C[S]
r = np.log(c).diff()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
fnd = F[S]
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)

k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
k = k.set_index("dt").sort_index()
lr = np.log(k["close"]).diff()
rv1 = (lr ** 2).groupby(lr.index.normalize()).sum().reindex(c.index)


def book(volx, mult=None, match=True):
    tgt = (0.40 / volx).clip(upper=1.0)
    if mult is not None:
        tgt = tgt * mult
    lw = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    sw = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (lw.fillna(0.0) - sw.fillna(0.0)).to_frame(S)
    if match:
        m = W[S].abs().loc["2020-06-01":].mean()
        W = W * (EXPO / m)
    return W, pd.Series(1.0, index=c.index)


def stats(W, A, label="", fee=lev.FEE):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True, fee=fee,
                                   start="2020-06-01", spot_base=True)
    x = ret.loc["2020-06-01":]
    e = (1 + x).cumprod()
    dd = (e / e.cummax() - 1)
    h = len(x) // 2
    sh = lambda s: s.mean() / s.std() * np.sqrt(BPY)
    cagr = (e.iloc[-1] ** (BPY / len(x)) - 1) * 100
    # turnover: total notional traded per year
    dW = (W[S] * A).diff().abs()
    turn = dW.loc["2020-06-01":].sum() / (len(x) / BPY)
    return dict(cfg=label, cagr=cagr, vol=x.std() * np.sqrt(BPY) * 100, sharpe=sh(x),
                mdd=dd.min() * 100, calmar=cagr / abs(dd.min() * 100),
                h1=sh(x.iloc[:h]), h2=sh(x.iloc[h:]),
                turn=turn, cost=turn * fee * 2 * 100), x


print("=== 1. fast vs slow vol: cost or timing? (matched exposure, fee swept) ===")
rows = []
for nm, vv in [("cc60  (delivered)", vol), ("rv14 (fast)", np.sqrt(rv1.rolling(14, min_periods=7).mean() * BPY)),
               ("rv3  (fastest)", np.sqrt(rv1.rolling(3, min_periods=2).mean() * BPY))]:
    for fee in (0.0, 0.0004):
        W, A = book(vv.clip(lower=0.15))
        rows.append(stats(W, A, f"{nm} fee={fee*1e4:.0f}bp", fee=fee)[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 2. funding percentile: is it just a year proxy? ===")
yr = fnd.index.year
# causal within-year percentile: rank of today among this year's observations so far
fq_yr = fnd.groupby(yr).expanding(min_periods=20).apply(
    lambda s: (s.iloc[-1] > s).mean()).reset_index(level=0, drop=True).reindex(fnd.index)
# early in a year there are few prints; fall back to the trailing-year rank
fq_mix = fq_yr.where(fq_yr.notna() & (fnd.groupby(yr).cumcount() >= 20), fq)
fq_mix = fq_mix.fillna(0.5)

print(f"  corr(rolling-1y pct, within-year pct) = {fq.corr(fq_mix):.3f}")
print("  mean funding pct by year:")
print(pd.DataFrame({"rolling1y": fq.groupby(yr).mean(),
                    "within_year": fq_mix.groupby(yr).mean()}).round(3).to_string())

print("\n  the same tilt built on each version (theta=-0.50, exposure matched):")
rows = []
for nm, f in [("rolling 1y pct", fq), ("within-year pct", fq_mix)]:
    for th in (0.0, -0.25, -0.50):
        W, A = book(vol, mult=(f / 0.5).clip(0.2, 2.0).pow(th))
        rows.append(stats(W, A, f"{nm} theta {th:+.2f}")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== 3. year-by-year return (%), funding tilt ===")
ser = {}
for nm, f, th in [("delivered", fq, 0.0), ("1y pct -0.50", fq, -0.5),
                  ("within-yr -0.50", fq_mix, -0.5), ("within-yr -0.25", fq_mix, -0.25)]:
    W, A = book(vol, mult=(f / 0.5).clip(0.2, 2.0).pow(th))
    _, x = stats(W, A, nm)
    ser[nm] = x
yr_tab = pd.DataFrame({k: v.groupby(v.index.year).apply(lambda s: (1 + s).prod() - 1) * 100
                       for k, v in ser.items()})
print(yr_tab.round(1).to_string())

print("\n  2021 / 2022 detail (funding was extreme in both):")
for nm in ser:
    a = ser[nm].loc["2021"]
    b = ser[nm].loc["2022"]
    print(f"    {nm:18s} 2021 {(1+a).prod()*100-100:7.1f}%   2022 {(1+b).prod()*100-100:7.1f}%")

print("\n=== 4. paired block bootstrap: dSharpe vs delivered ===")
base = ser["delivered"].to_numpy()


def block_boot(a, b, n=2000, blk=20, seed=7):
    rng = np.random.default_rng(seed)
    m = min(len(a), len(b))
    a, b = a[-m:], b[-m:]
    nb = m // blk
    starts = rng.integers(0, m - blk, size=(n, nb))
    out = np.empty(n)
    for i in range(n):
        idx = (starts[i][:, None] + np.arange(blk)).ravel()
        xa, xb = b[idx], a[idx]          # b = candidate, a = base
        sa = xa.mean() / xa.std() * np.sqrt(BPY)
        sb = xb.mean() / xb.std() * np.sqrt(BPY)
        out[i] = sa - sb
    return out


for nm in ["1y pct -0.50", "within-yr -0.50", "within-yr -0.25"]:
    d = block_boot(base, ser[nm].to_numpy())
    print(f"  {nm:18s} dSharpe {d.mean():+.3f}  90% [{np.percentile(d,5):+.3f},"
          f" {np.percentile(d,95):+.3f}]  P(d<=0) {(d<=0).mean():.3f}")
