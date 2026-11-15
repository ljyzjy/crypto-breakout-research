"""Final accounting, on the engine that charges funding and checks liquidation.

Three cost items that the spot-era version never had to think about, now that the book can
use perps:
  1. a long perp pays funding. 11.6%/yr average, positive 88% of days. The base position
     (up to 1x) can be held in spot and pay nothing -- only the levered excess must be a perp.
  2. cash earns nothing. The book is flat ~70% of the time when unlevered.
  3. the perp short in the funding-gated short leg RECEIVES funding, which the engine already
     credits.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 220)
BPY = 365

C, O, H, L, F = lev.load_perp(("BTCUSDT",))
sym = "BTCUSDT"
c, o, h, l = (x[sym] for x in (C, O, H, L))
r = c.pct_change()
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
z = lev.zscore(C)[sym]
px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
fnd = F[sym]

W = lev.signal_weight(z.to_frame(sym), vol.to_frame(sym), enter=0.20,
                      target_vol=0.40, allow_short=False)
W = W[[sym]]


def ladder():
    a = pd.Series(1.0, index=c.index)
    a = a.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
    a = a.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
    return a.clip(1.0, 3.0)


# delta-neutral carry stream
f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
dn = fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)


def run(A, spot_base, with_carry, label):
    m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=F, liq=True,
                                   start="2020-06-01", spot_base=spot_base)
    gross = (W[sym].abs() * A).shift(1).fillna(0.0)
    idle = (1.0 - gross).clip(lower=0.0)
    carry = (idle / 1.5) * dn
    x = ret.loc["2020-06-01":]
    if with_carry:
        x = x + carry.loc[x.index]
    eq2 = (1 + x).cumprod()
    yrs = len(x) / BPY
    mdd = (eq2 / eq2.cummax() - 1).min()
    y = x.groupby(x.index.year).apply(lambda s: (1 + s).prod() - 1)
    return dict(cfg=label, cagr=(eq2.iloc[-1] ** (1 / yrs) - 1) * 100,
                vol=x.std() * np.sqrt(BPY) * 100,
                sharpe=x.mean() / x.std() * np.sqrt(BPY),
                mdd=mdd * 100, calmar=(eq2.iloc[-1] ** (1 / yrs) - 1) / abs(mdd),
                fund_pa=m["fund_pa"] * 100, liq=m["liq"], expo=m["expo"],
                carry=carry.loc[x.index].mean() * BPY * 100,
                y2022=y.get(2022, np.nan) * 100, y2025=y.get(2025, np.nan) * 100,
                y2026=y.get(2026, np.nan) * 100)


rows = []
rows.append(run(1.0, False, False, "1.0x  perp, no carry  (V3-equivalent)"))
rows.append(run(1.0, True, False, "1.0x  spot base"))
rows.append(run(1.0, True, True, "1.0x  spot base + carry"))
rows.append(run(ladder(), False, False, "V4 ladder, perp"))
rows.append(run(ladder(), True, False, "V4 ladder, spot base"))
rows.append(run(ladder(), True, True, "V4 ladder, spot base + carry"))
rows.append(run(1.5, True, True, "1.5x  spot base + carry"))
rows.append(run(2.0, True, True, "2.0x  spot base + carry"))

print("=== funding drag, then the whole thing ===")
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== how much funding the long leg pays ===")
for A, lbl in ((1.0, "1.0x flat"), (ladder(), "V4 ladder")):
    m, _, ret, _ = lev.simulate(W, A, C, O, H, L, funding=F, start="2020-06-01")
    m2, _, _, _ = lev.simulate(W, A, C, O, H, L, funding=F, start="2020-06-01",
                               spot_base=True)
    print(f"  {lbl:12s} funding paid {m['fund_pa'] * 100:5.2f}%/yr on equity "
          f"-> {m2['fund_pa'] * 100:5.2f}%/yr with spot base "
          f"(saves {(m['fund_pa'] - m2['fund_pa']) * 100:.2f}%/yr)")
