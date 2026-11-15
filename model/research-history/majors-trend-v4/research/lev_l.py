"""Robustness of the leverage menu: halves, years, cliff location, real cost stress.

The 1x-6x Sharpe plateau is only useful if it holds out of the 2020-21 bull. This splits
the sample, walks each multiple year by year, locates the liquidation cliff precisely,
and re-runs the cost stress with `fee` passed explicitly (the default argument binds at
definition time, so mutating lev.FEE does nothing).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_d import running_dd
from lev_f import final_rules

pd.set_option("display.width", 280)
pd.set_option("display.max_columns", 40)


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]
    W, *_ = final_rules(C[sym], vol[sym], z[sym], f)

    print("=" * 128)
    print("A. 分年收益（固定杠杆）：高杠杆的收益是否只来自 2020-21")
    print("=" * 128)
    tab = {}
    for A in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        _, _, ret, _ = lev.simulate(W, A, *args, **kw)
        tab[f"{A:.1f}x"] = ((1 + ret).groupby(ret.index.year).prod() - 1) * 100
    tab["BTC"] = ((1 + C["BTCUSDT"].pct_change().reindex(ret.index))
                  .groupby(ret.index.year).prod() - 1) * 100
    print(pd.DataFrame(tab).round(1).to_string())

    print("\n" + "=" * 128)
    print("B. 分半样本（前半 2020-01~2023-03 / 后半 2023-04~2026-10）")
    print("=" * 128)
    rows = []
    for A in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
        _, _, ret, _ = lev.simulate(W, A, *args, **kw)
        d = {}
        for nm, sl in (("前", slice("2020-01-01", "2023-03-31")),
                       ("后", slice("2023-04-01", None))):
            s = ret.loc[sl]
            eq = (1 + s).cumprod()
            d[f"{nm}CAGR"] = (eq.iloc[-1] ** (365 / len(s)) - 1) * 100
            d[f"{nm}Sharpe"] = s.mean() / s.std() * np.sqrt(365)
            d[f"{nm}MDD"] = (eq / eq.cummax() - 1).min() * 100
        rows.append(dict(杠杆=f"{A:.1f}x", **d))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n" + "=" * 128)
    print("C. 悬崖精确定位：6x 以上哪里断")
    print("=" * 128)
    rows = []
    for A in (5.5, 6.0, 6.5, 7.0, 7.5, 8.0):
        m, eq, ret, log = lev.simulate(W, A, *args, **kw)
        m["cfg"] = f"{A:.1f}x"
        m["首强平"] = log[0]["dt"].date() if log else "-"
        rows.append(m)
    print(show(rows, cols=("cfg", "cagr", "vol", "sharpe", "mdd", "calmar", "liq", "首强平", "expo")))

    print("\n" + "=" * 128)
    print("D. 成本压力测试（fee 显式传入）：taker 4bp→8bp→12bp")
    print("=" * 128)
    rows = []
    for A in (1.5, 2.0, 2.5, 3.0):
        for feeb in (4, 8, 12):
            m, *_ = lev.simulate(W, A, *args, fee=feeb / 1e4, **kw)
            m["cfg"] = f"{A:.1f}x  {feeb}bp"
            rows.append(m)
    print(show(rows))

    print("\n" + "=" * 128)
    print("E. 滑点压力：把成交价按不利方向移动 5bp / 10bp 再重算（用 hs 近似）")
    print("=" * 128)
    print("  说明：逐日调仓幅度小，滑点主要打在新开/平仓日。用 fee 已覆盖 taker，")
    print("        额外滑点等价于 fee 上调；见 D 节 8bp/12bp 两行。")

    print("\n" + "=" * 128)
    print("F. 推荐刻度：Calmar 最优区与心理可承受区")
    print("=" * 128)
    best = []
    for A in np.arange(1.0, 4.01, 0.25):
        m, *_ = lev.simulate(W, float(A), *args, **kw)
        best.append(dict(A=float(A), cagr=m["cagr"] * 100, mdd=m["mdd"] * 100,
                         calmar=m["calmar"], sharpe=m["sharpe"], vol=m["vol"] * 100))
    d = pd.DataFrame(best)
    d["Calmar"] = d["calmar"].round(2)
    print(d[["A", "cagr", "mdd", "Calmar", "sharpe", "vol"]].round(2).to_string(index=False))
    print(f"\n  Calmar 最高: {d.loc[d['calmar'].idxmax(), 'A']:.2f}x  "
          f"(CAGR {d['cagr'].max():.1f}% 附近, MDD {d.loc[d['calmar'].idxmax(), 'mdd']:.1f}%)")
    print(f"  回撤 <= 35% 可承受的最高杠杆: "
          f"{d.loc[d['mdd'] >= -35.0, 'A'].max():.2f}x  "
          f"→ CAGR {d.loc[d['mdd'] >= -35.0, 'cagr'].iloc[-1]:.1f}%")
    print(f"  回撤 <= 45% 可承受的最高杠杆: "
          f"{d.loc[d['mdd'] >= -45.0, 'A'].max():.2f}x  "
          f"→ CAGR {d.loc[d['mdd'] >= -45.0, 'cagr'].iloc[-1]:.1f}%")


if __name__ == "__main__":
    main()
