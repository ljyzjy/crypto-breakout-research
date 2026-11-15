"""The delivered V4 reproduced exactly, then the two instrument fixes applied.

V4 = long z-weight + funding-gated short + 1.75/1.25/1.0 ladder.
Fix 1: hold the base long in spot. A long perp pays 11.6%/yr funding; spot pays none.
Fix 2: run the delta-neutral carry sleeve on the capital that is idle when flat.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 220)
BPY = 365
S = "BTCUSDT"

C, O, H, L, F = lev.load_perp((S,))
c = C[S]
r = c.pct_change()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[S]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[S]

tgt = (0.40 / vol).clip(upper=1.0)
long_w = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
# funding gate: only short when funding is rich vs its own trailing year
fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)
short_w = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
W = (long_w.fillna(0.0) - short_w.fillna(0.0)).to_frame(S)

A = pd.Series(1.0, index=c.index)
A = A.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
A = A.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
A = A.clip(1.0, 3.0)

f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
dn = fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)


def run(spot_base, carry, lev_mult=1.0, label=""):
    m, eq, ret, liq = lev.simulate(W, A * lev_mult, C, O, H, L, funding=F,
                                   liq=True, start="2020-06-01", spot_base=spot_base)
    x = ret.loc["2020-06-01":]
    if carry:
        gross = (W[S].abs() * A * lev_mult).shift(1).fillna(0.0)
        idle = (1.0 - gross).clip(lower=0.0)
        x = x + ((idle / 1.5) * dn).loc[x.index]
    eq2 = (1 + x).cumprod()
    yrs = len(x) / BPY
    dd = (eq2 / eq2.cummax() - 1)
    y = x.groupby(x.index.year).apply(lambda s: (1 + s).prod() - 1)
    return dict(cfg=label, cagr=(eq2.iloc[-1] ** (1 / yrs) - 1) * 100,
                vol=x.std() * np.sqrt(BPY) * 100,
                sharpe=x.mean() / x.std() * np.sqrt(BPY),
                mdd=dd.min() * 100, calmar=(eq2.iloc[-1] ** (1 / yrs) - 1) / abs(dd.min()),
                fund=m["fund_pa"] * 100, liq=m["liq"],
                y22=y.get(2022, np.nan) * 100, y25=y.get(2025, np.nan) * 100,
                y26=y.get(2026, np.nan) * 100), x


rows = []
series = {}
for sb, ca, lm, lbl in ((False, False, 1.0, "V4 as delivered (all perp)"),
                        (True, False, 1.0, "+ base long in spot"),
                        (True, True, 1.0, "+ carry on idle cash"),
                        (True, True, 1.25, "  ... at 1.25x"),
                        (True, True, 1.5, "  ... at 1.50x")):
    m, x = run(sb, ca, lm, lbl)
    rows.append(m)
    series[lbl.strip()] = x

print("=== V4, then instrument fixes ===")
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== per-year (%) ===")
t = pd.DataFrame(series)
print((t.groupby(t.index.year).apply(lambda d: (1 + d).prod() - 1) * 100).round(1).to_string())

print("\n=== split-half Sharpe ===")
for nm, x in series.items():
    h = len(x) // 2
    print(f"  {nm:28s} H1 {x.iloc[:h].mean() / x.iloc[:h].std() * np.sqrt(BPY):5.2f}"
          f"   H2 {x.iloc[h:].mean() / x.iloc[h:].std() * np.sqrt(BPY):5.2f}")
