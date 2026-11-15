"""Two loose ends: does funding also gate the long side, and where should the risk
budget sit? Both are cheap and decide the final parameter set.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_d import schedule, running_dd

pd.set_option("display.width", 240)


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]

    Wl = lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40)
    Ws = (lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40, allow_short=True) - Wl)

    print("=== A. 多空两侧各自加资金费门（2x）")
    rows = []
    qs = f.quantile(0.40)
    for lg in (0, 1):
        for sg in (0, 1):
            W = Wl.mul((f < f.quantile(0.75)).astype(float) if lg else 1.0, axis=0) \
                + Ws.mul((f > qs).astype(float) if sg else 1.0, axis=0)
            m, *_ = lev.simulate(W, 2, *args, **kw)
            m["cfg"] = f"多头门 {'开' if lg else '关'} / 空头门 {'开' if sg else '关'}"
            rows.append(m)
    print(show(rows))

    print("\n=== B. 多头门阈值扫描（空头门固定 40 分位，2x）")
    rows = []
    for q in (0.60, 0.75, 0.85, 0.95, 1.01):
        W = Wl.mul((f < f.quantile(q) if q <= 1 else pd.Series(True, index=f.index)).astype(float),
                   axis=0) + Ws.mul((f > qs).astype(float), axis=0)
        m, *_ = lev.simulate(W, 2, *args, **kw)
        m["cfg"] = f"多头仅在资金费<{min(q,1):.0%}分位"
        rows.append(m)
    print(show(rows))

    print("\n=== C. 风险预算细扫（条件倍率，多空+空头门）")
    Wls = Wl + Ws.mul((f > qs).astype(float), axis=0)
    _, _, r1x, _ = lev.simulate(Wls, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)
    rows = []
    for rb in (0.20, 0.30, 0.40, 0.50, 0.65, 0.80, 1.00, 1.30, 1.60):
        A = schedule(vol["BTCUSDT"], dd, risk_budget=rb, cap=5.0)
        m, *_ = lev.simulate(Wls, A, *args, **kw)
        m["cfg"] = f"预算{int(rb*100)}%  A中位{A.median():.2f}x 最大{A.max():.1f}x"
        rows.append(m)
    print(show(rows))

    print("\n=== D. 若禁用回撤减速")
    rows = []
    for rb in (0.50, 0.80, 1.00):
        A0 = schedule(vol["BTCUSDT"], dd, risk_budget=rb, cap=5.0)
        A1 = schedule(vol["BTCUSDT"], pd.Series(0.0, index=dd.index), risk_budget=rb, cap=5.0)
        for lab, A_ in (("带减速", A0), ("不带", A1)):
            m, *_ = lev.simulate(Wls, A_, *args, **kw)
            m["cfg"] = f"预算{int(rb*100)}% {lab}"
            rows.append(m)
    print(show(rows))


if __name__ == "__main__":
    main()
