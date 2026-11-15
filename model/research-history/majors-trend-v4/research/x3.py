"""Does the crypto cross-section diversify a trend book? The core CTA claim.

Earlier this project concluded "basket = disguised leverage". That verdict came from
adding coins at constant weight, i.e. raising risk. The actual CTA result is different:
more markets at the *same portfolio risk* should raise Sharpe, because the extra markets
lower portfolio vol faster than they lower return.

So: hold portfolio vol fixed at 40% and compare 1 coin against 24.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab

pd.set_option("display.width", 220)
BPY = 365


def bt(W, C, O, target=0.40, cap=2.5, cost=0.0010, start="2020-06-01",
       volwin=60, label=""):
    fwd = O.shift(-1) / O - 1
    raw = (W.shift(1) * fwd).sum(axis=1)
    rv = raw.rolling(volwin, min_periods=30).std() * np.sqrt(BPY)
    sc = (target / rv.shift(1)).clip(upper=cap)
    We = W.mul(sc, axis=0)
    gross = (We.shift(1) * fwd).sum(axis=1)
    turn = (We - We.shift(1)).abs().sum(axis=1)
    ret = (gross - turn * cost).loc[start:]
    eq = (1 + ret).cumprod()
    yrs = len(ret) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    out = dict(name=label, n=len(ret), cagr=(eq.iloc[-1] ** (1 / yrs) - 1) * 100,
               vol=ret.std() * np.sqrt(BPY) * 100,
               sharpe=ret.mean() / ret.std() * np.sqrt(BPY),
               mdd=mdd * 100, calmar=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(mdd),
               turn=turn.loc[start:].mean() * BPY,
               cost_pa=turn.loc[start:].mean() * cost * BPY * 100,
               expo=We.abs().sum(axis=1).loc[start:].mean(),
               scale=sc.loc[start:].mean())
    return out, ret, eq


C, O, H, L, V = lab.load_panel()
idx = C.index
r = C.pct_change()
valid = C.notna() & (V.fillna(0) > 0)
dv = V.rolling(30, min_periods=15).median()
uni = valid & (dv > 3e6) & (valid.cumsum() >= 250)

# same rule for every coin, no per-coin tuning
z = lab.zscore(C)
vol = r.rolling(60, min_periods=30).std() * np.sqrt(BPY)
core = z.clip(lower=0, upper=1.0) * (0.40 / vol).clip(upper=1.0)
core = core.where(z > 0.20, 0.0).where(uni, 0.0).fillna(0.0)

if __name__ == "__main__":
    rows, rets = [], {}
    btc = core[["BTCUSDT"]]
    rows.append(bt(btc, C, O, label="BTC only")[0]); rets["BTC"] = bt(btc, C, O)[1]

    alts = [c for c in core.columns if c != "BTCUSDT"]
    for k in (3, 6, 12, len(alts)):
        top = alts[:k]
        W = core[top] / k            # equal risk per coin
        o, ret, _ = bt(W, C, O, label=f"alts only, {k} coins")
        rows.append(o); rets[f"alt{k}"] = ret

    # all 24, equal risk
    W = core / len(core.columns)
    o, ret, _ = bt(W, C, O, label="all 24 equal risk")
    rows.append(o); rets["all24"] = ret

    print("=== same 40% portfolio vol target, trend long-only, 10bp per side ===")
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n=== correlation of daily returns (2020-06 onward) ===")
    R = pd.DataFrame(rets).dropna()
    print(R.corr().round(2).to_string())
    print("\nBTC vs all24: corr %.3f" % R["BTC"].corr(R["all24"]))

    print("\n=== 50/50 risk split: BTC book + alt book ===")
    for k in ("alt3", "alt6", "alt12", "all24"):
        cb = 0.5 * R["BTC"] + 0.5 * R[k]
        eq = (1 + cb).cumprod()
        yrs = len(cb) / BPY
        mdd = (eq / eq.cummax() - 1).min()
        print(f"  BTC + {k:6s}  CAGR {(eq.iloc[-1] ** (1 / yrs) - 1) * 100:6.1f}%  "
              f"vol {cb.std() * np.sqrt(BPY) * 100:5.1f}%  "
              f"Sharpe {cb.mean() / cb.std() * np.sqrt(BPY):5.2f}  MDD {mdd * 100:6.1f}%")

    print("\n=== per-year Sharpe, BTC vs all24 ===")
    for k in ("BTC", "all24"):
        y = R[k].groupby(R.index.year).agg(lambda x: x.mean() / x.std() * np.sqrt(BPY))
        print(f"  {k:6s} " + "  ".join(f"{i}:{v:5.2f}" for i, v in y.items()))
