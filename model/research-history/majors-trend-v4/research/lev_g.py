"""Tiered leverage ladder that refuses to lever up into low volatility.

The vol-inverse rule hands its highest multiple (1.7x) to the sigma<30% bucket, which is
the only losing bucket (-47%/yr): quiet tape in crypto is usually the top, not safety.
So the ladder caps the top tier and keys the rest on drawdown plus trend quality.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_d import running_dd
from lev_f import final_rules

pd.set_option("display.width", 250)


def ladder(vol_t, dd_t, z_t, tiers=(2.0, 1.5, 1.0)):
    """Three tiers, decided by (trend ok, vol moderate, drawdown shallow).

    Tier 0 (highest) requires all three: z>0.2, sigma<45%, dd>-10%.
    Tier 1 requires sigma<60% and dd>-20%.
    Tier 2 otherwise. Never above `tiers[0]`.
    """
    a = pd.Series(tiers[2], index=vol_t.index)
    t1 = (vol_t < 0.60) & (dd_t > -0.20)
    a = a.mask(t1, tiers[1])
    t0 = (vol_t < 0.45) & (dd_t > -0.10) & (z_t > 0.20)
    a = a.mask(t0, tiers[0])
    return a


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]
    W, Wl, Ws, gate = final_rules(C[sym], vol[sym], z[sym], f)

    _, _, r1x, _ = lev.simulate(W, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)

    print("=== A. 固定倍率参照")
    rows = []
    for A in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
        m, *_ = lev.simulate(W, A, *args, **kw)
        m["cfg"] = f"固定 {A}x"
        rows.append(m)
    print(show(rows))

    print("\n=== B. 分层阶梯（顶档 2x / 中 1.5x / 底 1x）")
    rows = []
    for tiers in ((2.0, 1.5, 1.0), (1.75, 1.25, 1.0), (2.5, 1.5, 1.0), (3.0, 2.0, 1.0),
                  (2.0, 1.0, 1.0)):
        A = ladder(vol["BTCUSDT"], dd, z["BTCUSDT"], tiers=tiers)
        m, *_ = lev.simulate(W, A, *args, **kw)
        m["cfg"] = f"阶梯 {tiers}  实际 {A.min():.1f}-{A.max():.1f}x 均值{A.mean():.2f}"
        rows.append(m)
    print(show(rows))

    print("\n=== C. 阶梯 vs 固定 1.5x：分年")
    A = ladder(vol["BTCUSDT"], dd, z["BTCUSDT"])
    _, _, rL, _ = lev.simulate(W, A, *args, **kw)
    _, _, r15, _ = lev.simulate(W, 1.5, *args, **kw)
    _, _, r10, _ = lev.simulate(W, 1.0, *args, **kw)
    t = pd.DataFrame({
        "阶梯": ((1 + rL).groupby(rL.index.year).prod() - 1) * 100,
        "固定1.5x": ((1 + r15).groupby(r15.index.year).prod() - 1) * 100,
        "固定1x": ((1 + r10).groupby(r10.index.year).prod() - 1) * 100,
        "BTC": ((1 + C["BTCUSDT"].pct_change().reindex(rL.index))
                .groupby(rL.index.year).prod() - 1) * 100,
    })
    print(t.round(1).to_string())

    print("\n=== D. 倍率实际分布（阶梯）")
    print(A.value_counts().sort_index().to_frame("天数").assign(
        占比=lambda x: (x["天数"] / len(A) * 100).round(0)).to_string())
    seg = pd.DataFrame({"A": A, "ret": rL}).dropna()
    print("\n各档位的实际年化：")
    for a_, s in seg.groupby("A"):
        print(f"  {a_:.2f}x  {len(s):4d} 天  {((1+s.ret).prod()**(365/len(s))-1)*100:+7.1f}%/yr")


if __name__ == "__main__":
    main()
