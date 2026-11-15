"""Carry: the other half of the CTA book. Delta-neutral funding harvest.

Every multi-premia shop runs trend and carry side by side because they are the two
premia that survive in every asset class and they are close to uncorrelated. Crypto has
an unusually large one: perp funding.

Position: long spot 1 unit, short perp 1 unit. Delta zero. Earns funding, loses basis
drift. Capital = 1.0 spot + 0.5 margin (spot cannot collateralise a USD-M short on
Binance), so 1.5 per unit notional.

Then the question that actually matters for this project: the trend book sits in cash
~54% of the time, earning nothing. Can that idle capital run carry instead?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab
from x3 import bt, core, C, O

pd.set_option("display.width", 220)
BPY = 365
CAP = 1.5          # capital per 1 unit of delta-neutral notional
FEE_SPOT = 0.0010  # taker
FEE_PERP = 0.0004

f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()

k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last()

idx = C.index
spot = C["BTCUSDT"]
perp = perp.reindex(idx).ffill(limit=2)
basis = (perp / spot - 1.0)
fund = fund.reindex(idx).fillna(0.0)

# delta-neutral daily P&L per unit notional: receive funding, mark basis drift
dn = fund - basis.diff().fillna(0.0)
dn = dn.loc["2020-06-01":]

print("=== delta-neutral BTC carry, per unit notional ===")
y = dn.groupby(dn.index.year)
tab = pd.DataFrame({
    "ann_%": y.mean() * BPY * 100,
    "vol_%": y.std() * np.sqrt(BPY) * 100,
    "pos_%": y.apply(lambda s: (s > 0).mean() * 100),
    "worst_day_bp": y.min() * 1e4,
})
tab["sharpe"] = tab["ann_%"] / tab["vol_%"]
print(tab.round(2).to_string())

eq = (1 + dn).cumprod()
mdd = (eq / eq.cummax() - 1).min()
print(f"\nfull period: ann {dn.mean() * BPY * 100:.2f}%  vol {dn.std() * np.sqrt(BPY) * 100:.2f}%  "
      f"Sharpe {dn.mean() / dn.std() * np.sqrt(BPY):.2f}  MDD {mdd * 100:.1f}%  "
      f"worst day {dn.min() * 1e4:.0f}bp")
print(f"on capital (x{1 / CAP:.2f}): ann {dn.mean() * BPY / CAP * 100:.2f}%  "
      f"vol {dn.std() * np.sqrt(BPY) / CAP * 100:.2f}%  "
      f"Sharpe {dn.mean() / dn.std() * np.sqrt(BPY):.2f}  MDD {mdd / CAP * 100:.1f}%")

print("\n=== correlation with the trend book ===")
_, trend_r, _ = bt(core[["BTCUSDT"]], C, O)
j = pd.DataFrame({"trend": trend_r, "carry": dn}).dropna()
print(f"  corr {j['trend'].corr(j['carry']):+.3f}  n={len(j)}")

print("\n=== capital budget: trend + carry sleeve ===")
print("  (carry sleeve f of equity, notional f/1.5; trend gets the rest)")
rows = []
for fc in (0.0, 0.15, 0.30, 0.45):
    tr = trend_r * (1 - fc)
    ca = dn * (fc / CAP)
    x = (tr + ca).dropna()
    # entry cost amortised over the whole path is tiny; charge it once per year of roll
    x = x - (FEE_SPOT + FEE_PERP) * (fc / CAP) * 4 / BPY
    eq = (1 + x).cumprod()
    yrs = len(x) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    rows.append(dict(carry_frac=fc, cagr=(eq.iloc[-1] ** (1 / yrs) - 1) * 100,
                     vol=x.std() * np.sqrt(BPY) * 100,
                     sharpe=x.mean() / x.std() * np.sqrt(BPY),
                     mdd=mdd * 100, calmar=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(mdd)))
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== same, but the alternative is just leveraging trend up ===")
for lev in (1.0, 1.15, 1.3, 1.5):
    x = (trend_r * lev).dropna()
    eq = (1 + x).cumprod()
    yrs = len(x) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    print(f"  trend x{lev:.2f}: CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:6.1f}%  "
          f"vol {x.std() * np.sqrt(BPY) * 100:5.1f}%  "
          f"Sharpe {x.mean() / x.std() * np.sqrt(BPY):5.2f}  MDD {mdd * 100:6.1f}%")
