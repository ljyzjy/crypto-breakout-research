"""Conviction tilt vs a leverage-matched control.

The only honest test of "leverage up where I am confident": hold average exposure
constant and move the leverage around in time. If the tilt version beats the flat
version at the same mean A, conviction has value. If it only beats A=1.0 but loses to
the matched flat version, the tilt is leverage in disguise.

Note w already scales with clip(z,0,1), so A(z) makes exposure quadratic in z.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_d import running_dd
from lev_f import final_rules

pd.set_option("display.width", 260)


def tilt_A(z_abs, vol, dd, budget=0.50, cap=5.0, tiers=((0.80, 1.30), (1.30, 1.60)),
           dd_soft=-0.15, dd_hard=-0.30, soft=0.7, hard=0.4):
    """Constant-risk base, multiplied up when |z| clears a tier, throttled in drawdown."""
    a = (budget / vol).clip(1.0, cap)
    for thr, mult in tiers:
        a = a.where(z_abs <= thr, a * mult)
    th = pd.Series(1.0, index=a.index)
    th = th.mask(dd < dd_soft, soft).mask(dd < dd_hard, hard)
    return (a * th).clip(1.0, cap)


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]
    W, Wl, Ws, gate = final_rules(C[sym], vol[sym], z[sym], f)
    _, _, r1x, _ = lev.simulate(W, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)
    za = z["BTCUSDT"].abs().shift(1)

    cfgs = {
        "V4 基准 预算50%": tilt_A(za, vol["BTCUSDT"], dd, 0.50, 5.0, tiers=()),
        "倾斜 预算50% ×(1.3/1.6)": tilt_A(za, vol["BTCUSDT"], dd, 0.50, 5.0,
                                        tiers=((0.80, 1.30), (1.30, 1.60))),
        "倾斜 预算50% ×(1.5/2.0)": tilt_A(za, vol["BTCUSDT"], dd, 0.50, 5.0,
                                        tiers=((0.80, 1.50), (1.30, 2.00))),
        "倾斜 预算35% ×(1.5/2.2)": tilt_A(za, vol["BTCUSDT"], dd, 0.35, 5.0,
                                        tiers=((0.60, 1.50), (1.20, 2.20))),
        "倾斜 预算35% ×(1.8/2.6)": tilt_A(za, vol["BTCUSDT"], dd, 0.35, 5.0,
                                        tiers=((0.60, 1.80), (1.20, 2.60))),
    }
    print("=" * 118)
    print("A. 各方案（平均敞口要可比，否则比较无效）")
    print("=" * 118)
    res, curves = {}, {}
    for nm, A in cfgs.items():
        m, eq, ret, log = lev.simulate(W, A, *args, **kw)
        m["cfg"] = f"{nm}  [A均{A.mean():.2f} {A.min():.1f}-{A.max():.1f}x]"
        res[nm] = m
        curves[nm] = (eq, ret, A)
    print(show(list(res.values())))

    print("\n" + "=" * 118)
    print("B. 杠杆匹配对照：固定 A = 倾斜版的实际平均 A（同样敞口，不择时）")
    print("=" * 118)
    rows = []
    for nm in list(cfgs)[1:]:
        A = cfgs[nm]
        am = float(A.mean())
        for lab_, av in ((f"匹配 A={am:.2f}x 固定", am),):
            m, eq, ret, log = lev.simulate(W, av, *args, **kw)
            m["cfg"] = f"{lab_}   <-> {nm}"
            rows.append(m)
            curves[f"固定{av:.2f}"] = (eq, ret, None)
    print(show(rows))

    print("\n" + "=" * 118)
    print("C. 结论对照表：倾斜版 vs 它自己的匹配固定版（同时列出 Sharpe 与 Calmar 差）")
    print("=" * 118)
    print(f"{'方案':<28}{'A均':>5}{'CAGR':>8}{'MDD':>8}{'Sharpe':>8}{'Calmar':>8}"
          f"   |  {'匹配固定A':>10}{'CAGR':>8}{'MDD':>8}{'Sharpe':>8}{'Calmar':>8}   判定")
    for nm in list(cfgs)[1:]:
        A = cfgs[nm]
        am = float(A.mean())
        mt, _, _, _ = lev.simulate(W, am, *args, **kw)
        t = res[nm]
        verdict = ("倾斜胜" if (t["sharpe"] > mt["sharpe"] and t["calmar"] > mt["calmar"])
                   else "固定胜" if (t["sharpe"] < mt["sharpe"] and t["calmar"] < mt["calmar"])
                   else "打平/混合")
        print(f"{nm:<28}{am:>5.2f}{t['cagr']*100:>7.1f}%{t['mdd']*100:>7.1f}%"
              f"{t['sharpe']:>8.2f}{t['calmar']:>8.2f}   |  {'固定':>10}{mt['cagr']*100:>7.1f}%"
              f"{mt['mdd']*100:>7.1f}%{mt['sharpe']:>8.2f}{mt['calmar']:>8.2f}   {verdict}")

    print("\n" + "=" * 118)
    print("D. 分年（倾斜 vs 匹配固定）")
    print("=" * 118)
    t = {}
    A = cfgs["倾斜 预算35% ×(1.8/2.6)"]
    am = float(A.mean())
    _, _, rt, _ = lev.simulate(W, A, *args, **kw)
    _, _, rm, _ = lev.simulate(W, am, *args, **kw)
    t["倾斜35%×1.8"] = ((1 + rt).groupby(rt.index.year).prod() - 1) * 100
    t[f"固定{am:.2f}x"] = ((1 + rm).groupby(rm.index.year).prod() - 1) * 100
    t["BTC"] = ((1 + C["BTCUSDT"].pct_change().reindex(rt.index))
                .groupby(rt.index.year).prod() - 1) * 100
    print(pd.DataFrame(t).round(1).to_string())

    print("\n" + "=" * 118)
    print("E. 强平约束下的理论上限：A < 1/(mm + k*sig_d)，及其历史可用值")
    print("=" * 118)
    sigd = vol["BTCUSDT"] / np.sqrt(365)
    for k in (2.0, 3.0, 4.0):
        lim = 1.0 / (lev.MM + k * sigd)
        print(f"  k={k:.0f}: 上限中位 {lim.median():5.1f}x   p10 {lim.quantile(.1):5.1f}x   "
              f"最高 {lim.max():5.1f}x   达 40x 的天数 {int((lim>=40).sum())}")
        print(f"        达 10x 的天数 {int((lim>=10).sum())}   达 5x {int((lim>=5).sum())}   "
              f"低于 3x {int((lim<3).sum())}")

    print("\n" + "=" * 118)
    print("F. 把 A 直接推到强平上限会怎样（不同 k）")
    print("=" * 118)
    rows = []
    for k in (2.5, 3.0, 4.0):
        A = (1.0 / (lev.MM + k * sigd)).clip(1.0, 40.0)
        m, *_ = lev.simulate(W, A, *args, **kw)
        m["cfg"] = f"A=1/(mm+{k}σd) 中位{A.median():.1f}x 最大{A.max():.1f}x"
        rows.append(m)
    print(show(rows))


if __name__ == "__main__":
    main()
