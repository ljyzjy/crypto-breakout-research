"""The shipped file does not rebalance, so it is not the book that was measured.

BtcTrendV4.py sizes once in custom_stake_amount at entry and exits when mom_z < 0.  There
is no adjust_trade_position, so the weight is frozen for the whole holding period.  The
research book, meanwhile, walks to z * min(1, 0.4/vol) every single day: it scales down
as the trend weakens and as volatility rises.

Those are different books.  This measures the gap three ways:

  A. daily rebalance to target            -- what the numbers have always described
  B. size once at entry, hold until exit  -- what the file actually does
  C. B plus a rebalance only when the target has drifted past a band -- the fix

Everything else is identical: same entries, same exits, same ladder, same funding.
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

tgt = (z.clip(lower=0, upper=1.0) * (0.40 / vol).clip(upper=1.0)).where(z > 0.20, 0.0)
tsh = ((-z).clip(lower=0, upper=1.0) * (0.40 / vol).clip(upper=1.0)).where(
    (z < -0.20) & (fq > 0.40), 0.0)

A = pd.Series(1.0, index=c.index)
A = A.mask((vol < 0.60) & (px > -0.20), 1.25)
A = A.mask((vol < 0.45) & (px > -0.10) & (z > 0.20), 1.75)


def freeze(W, exit_below_zero=True):
    """hold the entry weight until the signal turns off (mom_z crosses 0)"""
    w = W.to_numpy().copy()
    out = np.zeros_like(w)
    held, side = 0.0, 0
    for i in range(len(w)):
        t = w[i]
        if side == 0:
            if t > 0:
                held, side = t, 1
        elif side > 0:
            if (exit_below_zero and z.iloc[i] < 0.0) or (not exit_below_zero and t <= 0):
                held, side = 0.0, 0
        else:
            if (exit_below_zero and z.iloc[i] > 0.0) or (not exit_below_zero and t >= 0):
                held, side = 0.0, 0
        if side == 0 and t < 0:
            held, side = t, -1
        out[i] = held
    return pd.Series(out, index=W.index)


def band(W, b):
    if b <= 0:
        return W
    held, out = 0.0, np.empty(len(W))
    for i, t in enumerate(W.to_numpy()):
        if abs(t - held) > b:
            held = t
        out[i] = held
    return pd.Series(out, index=W.index)


def run(w, label=""):
    W = w.to_frame(S)
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
                expo=W[S].abs().loc["2020-06-01":].mean(),
                turn=(W[S] * A).diff().abs().loc["2020-06-01":].sum() / (n / BPY)), x


raw = (tgt - tsh)
print("=== A/B/C: does the missing rebalance cost anything? ===")
rows = []
rows.append(run(raw, "A. daily rebalance (measured)")[0])
rows.append(run(freeze(raw), "B. size at entry, hold (the file)")[0])
rows.append(run(freeze(raw, exit_below_zero=False), "B'. hold until target hits 0")[0])
for b in (0.05, 0.10, 0.20):
    rows.append(run(band(raw, b), f"C. band {b:.2f} rebalance")[0])
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\n=== per-year (%) ===")
ser = {}
for nm, w in [("A daily", raw), ("B hold", freeze(raw)),
              ("B' hold to 0", freeze(raw, exit_below_zero=False)),
              ("C band .10", band(raw, 0.10))]:
    st, x = run(w, nm)
    ser[nm] = x
print(pd.DataFrame({k: v.groupby(v.index.year).apply(lambda s: (1 + s).prod() - 1) * 100
                    for k, v in ser.items()}).round(1).to_string())

print("\n=== how far does the held weight drift from target? ===")
h = freeze(raw)
drift = (h - raw)
print(f"  mean |drift| {drift.abs().loc['2020-06-01':].mean():.3f}"
      f"   p90 {drift.abs().loc['2020-06-01':].quantile(0.90):.3f}"
      f"   max {drift.abs().loc['2020-06-01':].max():.3f}")
print(f"  mean target {raw.abs().loc['2020-06-01':].mean():.3f}"
      f"   mean held {h.abs().loc['2020-06-01':].mean():.3f}")
