"""Two construction questions the spot-era code never had to answer.

1. `min(1, 0.4/vol)` caps notional at 1.0 whenever BTC vol < 40%, so realised risk falls
   below target exactly in the calm regimes trend likes. With perps there is no reason for
   that cap. Proper vol targeting is two-sided. Does removing the cap help or hurt?
   (Earlier work found the low-vol bucket was the *only* losing bucket, which predicts
   that removing the cap will hurt. Test it.)

2. The trend book is flat ~54% of the time and that cash earns nothing. Can it run the
   delta-neutral carry sleeve instead? Sized off actual idle capital, not a fixed budget.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab

pd.set_option("display.width", 220)
BPY = 365
COST = 0.0010

C, O, H, L, V = lab.load_panel()
idx = C.index
r = C.pct_change()
valid = C.notna() & (V.fillna(0) > 0)
dv = V.rolling(30, min_periods=15).median()
uni = valid & (dv > 3e6) & (valid.cumsum() >= 250)

z = lab.zscore(C)
vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
zpos = z.clip(lower=0, upper=1.0).where(z > 0.20, 0.0)
fwd = O.shift(-1) / O - 1


def book(cols, target=0.40, cap=1.0, cost=COST, start="2020-06-01"):
    w = (zpos[cols] * (target / vol[cols]).clip(upper=cap)).where(uni[cols], 0.0).fillna(0.0)
    w = w / len(cols)
    g = (w.shift(1) * fwd[cols]).sum(axis=1)
    turn = (w - w.shift(1)).abs().sum(axis=1)
    ret = (g - turn * cost).loc[start:]
    expo = w.abs().sum(axis=1).loc[start:]
    eq = (1 + ret).cumprod()
    yrs = len(ret) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    return dict(cagr=(eq.iloc[-1] ** (1 / yrs) - 1) * 100,
                vol=ret.std() * np.sqrt(BPY) * 100,
                sharpe=ret.mean() / ret.std() * np.sqrt(BPY),
                mdd=mdd * 100, calmar=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(mdd),
                expo=expo.mean(), turn=turn.loc[start:].mean() * BPY), ret, expo, w


print("=== 1. vol-target cap: 1.0 (spot-era) vs uncapped ===")
rows = []
for cap in (1.0, 1.5, 2.0, 3.0, 5.0):
    for tgt in (0.40,):
        m, _, _, _ = book(["BTCUSDT"], target=tgt, cap=cap)
        m["label"] = f"BTC cap {cap:.1f}x @{tgt:.0%}"
        rows.append(m)
for cap in (1.0, 2.0, 3.0):
    m, _, _, _ = book([c for c in C.columns], target=0.40, cap=cap)
    m["label"] = f"all24 cap {cap:.1f}x @40%"
    rows.append(m)
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== 2. same, split-half, to see if the answer is a regime artifact ===")
for cap in (1.0, 2.0, 3.0):
    _, ret, _, _ = book(["BTCUSDT"], cap=cap)
    h = len(ret) // 2
    s1 = ret.iloc[:h].mean() / ret.iloc[:h].std() * np.sqrt(BPY)
    s2 = ret.iloc[h:].mean() / ret.iloc[h:].std() * np.sqrt(BPY)
    print(f"  cap {cap:.1f}x: Sharpe H1 {s1:.2f}  H2 {s2:.2f}")

print("\n=== 3. realised vol vs target, cap 1.0 ===")
_, ret1, expo1, _ = book(["BTCUSDT"], cap=1.0)
_, ret3, expo3, _ = book(["BTCUSDT"], cap=3.0)
rv1 = ret1.rolling(90).std() * np.sqrt(BPY)
rv3 = ret3.rolling(90).std() * np.sqrt(BPY)
print(f"  cap1.0: median realised vol {rv1.median() * 100:.1f}%  "
      f"days below 30%: {(rv1 < 0.30).mean() * 100:.0f}%  avg expo {expo1.mean():.2f}")
print(f"  cap3.0: median realised vol {rv3.median() * 100:.1f}%  "
      f"days below 30%: {(rv3 < 0.30).mean() * 100:.0f}%  avg expo {expo3.mean():.2f}")

print("\n=== 4. idle-cash carry overlay (sized off actual idle capital) ===")
f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
f["dt"] = pd.to_datetime(f["dt"], utc=True)
fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
k["dt"] = pd.to_datetime(k["dt"], utc=True)
perp = k.set_index("dt")["close"].resample("1D").last().reindex(idx).ffill(limit=2)
basis = perp / C["BTCUSDT"] - 1.0
dn = (fund.reindex(idx).fillna(0.0) - basis.diff().fillna(0.0))

for cap in (1.0, 3.0):
    _, ret, expo, w = book(["BTCUSDT"], cap=cap)
    # idle built from the same weights, shifted the same way the P&L is
    idle = (1.0 - expo).clip(lower=0.0)
    carry = (idle.shift(1).fillna(0.0) / 1.5) * dn.reindex(idle.index)
    x = (ret + carry).dropna()
    eq = (1 + x).cumprod()
    yrs = len(x) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    print(f"  cap {cap:.1f}x  trend {(1 + ret).prod() ** (BPY / len(ret)) - 1:6.1%}  "
          f"->  +carry {(eq.iloc[-1]) ** (1 / yrs) - 1:6.1%}   "
          f"Sharpe {ret.mean() / ret.std() * np.sqrt(BPY):.2f} -> "
          f"{x.mean() / x.std() * np.sqrt(BPY):.2f}   "
          f"MDD {mdd * 100:.1f}%   carry adds {carry.mean() * BPY * 100:.1f}%/yr")
    print(f"      idle capital avg {idle.mean():.2f}, carry notional avg {(idle / 1.5).mean():.2f}, "
          f"carry contribution by year: "
          + " ".join(f"{y}:{v * BPY * 100:.1f}" for y, v in
                     (carry.groupby(carry.index.year).mean()).items()))
