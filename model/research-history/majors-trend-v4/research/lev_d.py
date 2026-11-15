"""Conditional leverage schedule.

The empirical facts that constrain the design:
  - 1x..5x: Sharpe is flat at 1.14. Leverage is pure scaling, not an edge.
  - 8x and above: one liquidation event ends the account. Not "a bad day", the end.
  - Therefore the schedule must live well inside the cliff, and its job is to hold
    risk constant, not to manufacture return.

Rule:  A_t = clip( risk_budget / sigma_t , 1, cap )   with a drawdown throttle.
`risk_budget` is the only free parameter and it maps directly to realised volatility,
so there is nothing to fit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_c import boot_sharpe_diff

pd.set_option("display.width", 240)


def schedule(vol_t, dd_t, risk_budget=0.35, cap=5.0, dd_soft=-0.15, dd_hard=-0.30,
             soft=0.7, hard=0.4):
    """A = risk_budget / vol, throttled while in drawdown, hard-capped below the cliff."""
    a = (risk_budget / vol_t).clip(1.0, cap)
    throttle = pd.Series(1.0, index=a.index)
    throttle = throttle.mask(dd_t < dd_soft, soft)
    throttle = throttle.mask(dd_t < dd_hard, hard)
    return (a * throttle).clip(1.0, cap)


def running_dd(ret):
    eq = (1 + ret.fillna(0)).cumprod()
    return eq / eq.cummax() - 1.0


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]

    Wl = lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40)
    Ws = (lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40, allow_short=True)
          - Wl)
    gate = (f > f.quantile(0.40)).astype(float)
    Wls = Wl + Ws.mul(gate, axis=0)

    # ---- drawdown of the 1x reference path, lagged so it is knowable today
    m1, eq1, r1, _ = lev.simulate(Wls, 1.0, *args, **kw)
    dd = running_dd(r1).shift(1).fillna(0.0)

    print("=== A. 规则化倍率 vs 固定倍率（多空+资金费门）")
    rows = []
    for A in (1, 2, 3, 4, 5):
        m, *_ = lev.simulate(Wls, float(A), *args, **kw)
        m["cfg"] = f"固定 {A}x"
        m["A_med"] = float(A)
        rows.append(m)
    configs = {}
    for rb in (0.25, 0.35, 0.50, 0.70, 1.00):
        A = schedule(vol["BTCUSDT"], dd, risk_budget=rb)
        m, eq, ret, log = lev.simulate(Wls, A, *args, **kw)
        m["cfg"] = f"条件倍率 预算{int(rb*100)}%"
        m["A_med"] = float(A.median())
        rows.append(m)
        configs[rb] = (A, ret, m)
    d = pd.DataFrame(rows)
    for c in ("cagr", "vol", "mdd", "fee_pa", "fund_pa", "expo"):
        d[c] = (d[c] * 100).round(1)
    print(d[["cfg", "A_med", "cagr", "vol", "sharpe", "mdd", "calmar", "liq", "fund_pa", "expo"]]
          .round(2).to_string(index=False))

    print("\n=== B. 倍率如何随条件变化（预算 35%）")
    A = configs[0.35][0]
    buckets = pd.cut(vol["BTCUSDT"], [0, .25, .40, .60, .90, 9.9],
                     labels=["σ<25%", "25-40%", "40-60%", "60-90%", "σ>90%"])
    t = pd.DataFrame({"A": A, "vol": vol["BTCUSDT"], "bucket": buckets,
                      "z": z["BTCUSDT"]}).dropna()
    g = t.groupby("bucket", observed=True)["A"].agg(["mean", "min", "max", "count"])
    g["占比"] = (g["count"] / len(t) * 100).round(0)
    print(g.round(2).to_string())

    print("\n=== C. 分年（预算 35% vs 固定 2x）")
    yrs = {}
    for lab, A_ in (("固定1x", 1.0), ("固定2x", 2.0), ("固定5x", 5.0)):
        _, _, rr, _ = lev.simulate(Wls, A_, *args, **kw)
        yrs[lab] = ((1 + rr).groupby(rr.index.year).prod() - 1) * 100
    _, _, rr, _ = lev.simulate(Wls, configs[0.35][0], *args, **kw)
    yrs["条件35%"] = ((1 + rr).groupby(rr.index.year).prod() - 1) * 100
    yrs["BTC"] = ((1 + C["BTCUSDT"].pct_change().reindex(rr.index))
                  .groupby(rr.index.year).prod() - 1) * 100
    print(pd.DataFrame(yrs).round(1).to_string())

    print("\n=== D. 预算是唯一参数：敏感性与自助区间")
    for rb in (0.25, 0.35, 0.50, 0.70):
        A_, ret_, m_ = configs[rb]
        mu, lo, hi, p = boot_sharpe_diff(configs[0.35][1], ret_, n=2000)
        print(f"  预算{int(rb*100):>3}%  A中位 {A_.median():.1f}x  CAGR {m_['cagr']*100:5.1f}%  "
              f"MDD {m_['mdd']*100:5.1f}%  Sharpe {m_['sharpe']:.2f}  "
              f"ΔSharpe(vs35%) {mu*365**0.5:+.2f} [{lo*365**0.5:+.2f},{hi*365**0.5:+.2f}]")

    print("\n=== E. 40x 对照：同样的信号，只改倍率")
    for A_ in (40.0,):
        m, eq, ret, log = lev.simulate(Wls, A_, *args, **kw)
        e = log[0] if log else None
        print(f"  40x  强平 {len(log)} 次，首次 {str(e['dt'])[:10]} 持仓 {(1+m['total']):.4f} 倍")


if __name__ == "__main__":
    main()
