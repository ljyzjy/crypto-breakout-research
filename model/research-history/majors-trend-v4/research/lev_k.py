"""If conviction does not pay, what does? Raw leverage, priced honestly.

Sharpe is flat across 1x-5x, so the return/drawdown menu is a straight line: every
extra point of CAGR costs a fixed amount of drawdown, until the liquidation cliff.
This maps that line, locates the cliff, and tests a drawdown throttle that cuts
leverage when the account is already hurt -- the opposite policy to a conviction tilt.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_d import running_dd
from lev_f import final_rules

pd.set_option("display.width", 260)


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]
    W, *_ = final_rules(C[sym], vol[sym], z[sym], f)
    _, _, r1x, _ = lev.simulate(W, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)

    print("=" * 122)
    print("A. 固定杠杆完整梯度：收益-回撤菜单，以及悬崖在哪")
    print("=" * 122)
    rows = []
    for A in (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0, 6.0):
        m, eq, ret, log = lev.simulate(W, A, *args, **kw)
        m["cfg"] = f"{A:.2f}x"
        rows.append(m)
    print(show(rows))

    print("\n" + "=" * 122)
    print("B. 每个杠杆的最坏单日 / 最坏单月（判断心理承受力）")
    print("=" * 122)
    out = []
    for A in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
        _, _, ret, log = lev.simulate(W, A, *args, **kw)
        mth = (1 + ret).groupby([ret.index.year, ret.index.month]).prod() - 1
        out.append(dict(杠杆=f"{A:.1f}x", 最坏单日=f"{ret.min()*100:.1f}%",
                        最坏单月=f"{mth.min()*100:.1f}%",
                        最坏年份=f"{((1+ret).groupby(ret.index.year).prod()-1).min()*100:.1f}%",
                        强平=len(log)))
    print(pd.DataFrame(out).to_string(index=False))

    print("\n" + "=" * 122)
    print("C. 回撤节流：杠杆在亏损后主动降低（与「信心加仓」相反的政策）")
    print("=" * 122)
    rows = []
    for base in (2.0, 2.5, 3.0):
        for soft, hard in ((-0.20, -0.35), (-0.25, -0.40)):
            A = pd.Series(base, index=C.index)
            A = A.mask(dd < soft, 1.0).mask(dd < hard, max(1.0, base - 1.0))
            m, *_ = lev.simulate(W, A, *args, **kw)
            m["cfg"] = f"基准{base}x 回撤{soft*100:.0f}%→1x {hard*100:.0f}%→{base-1:.0f}x (A均{A.mean():.2f})"
            rows.append(m)
    print(show(rows))

    print("\n" + "=" * 122)
    print("D. 成本敏感性：手续费/资金费翻倍时各杠杆还剩多少")
    print("=" * 122)
    rows = []
    for A in (1.5, 2.0, 2.5, 3.0):
        for mult in (1.0, 2.0, 3.0):
            old = lev.FEE
            lev.FEE = old * mult
            m, *_ = lev.simulate(W, A, *args, **kw)
            lev.FEE = old
            m["cfg"] = f"{A:.1f}x 成本×{mult:.0f}"
            rows.append(m)
    print(show(rows))

    print("\n" + "=" * 122)
    print("E. 若真按「强平距离 = 3 个日波动」定杠杆，历史上 A 分别落在哪")
    print("=" * 122)
    sigd = vol["BTCUSDT"] / np.sqrt(365)
    lim = 1.0 / (lev.MM + 3.0 * sigd)
    print("  理论上限 (k=3) 分位: " + "  ".join(
        f"p{int(q*100)}={lim.quantile(q):.1f}x" for q in (.05, .25, .5, .75, .95)))
    print(f"  实际能同时满足「A>=N」与「A<=上限」的天数：")
    for want in (2, 3, 5, 8, 10, 20, 40):
        print(f"    A>={want:2d}x 可用 {int((lim>=want).sum()):4d} 天 "
              f"({(lim>=want).mean()*100:4.1f}%)")

    # save dashboards
    m, eq, ret, _ = lev.simulate(W, 2.0, *args, **kw)
    pd.DataFrame({"equity_1x": lev.simulate(W, 1.0, *args, **kw)[1],
                  "equity_2x": eq}).to_csv("out/lev_menu.csv")


if __name__ == "__main__":
    main()
