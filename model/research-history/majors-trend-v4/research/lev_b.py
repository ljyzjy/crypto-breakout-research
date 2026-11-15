"""Long/short on perps. Shorts earn funding when it is positive, and die in squeezes.

The interesting question is not "does shorting add return" (it does, mechanically, in a
bear market) but "does it add return per unit of drawdown once you charge funding and
liquidation risk".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show

pd.set_option("display.width", 220)


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")

    print(f"样本 {C.index[0].date()} -> {C.index[-1].date()}  |  "
          f"BTC 同期 {(C['BTCUSDT'].iloc[-1]/C['BTCUSDT'].iloc[0]-1)*100:.0f}%")
    print("资金费 多头日均 %.2f bp（正数=多头付出）" % (F["BTCUSDT"].mean() * 1e4))

    Wl = lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40, allow_short=False)
    Ws = lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40, allow_short=True) - Wl

    print("\n=== A. 单边方向")
    rows = []
    for A in (1, 2, 3, 5):
        m, *_ = lev.simulate(Wl, A, *args, **kw)
        m["cfg"] = f"只做多 {A}x"
        rows.append(m)
    for A in (1, 2, 3, 5):
        m, *_ = lev.simulate(Ws, A, *args, **kw)
        m["cfg"] = f"只做空 {A}x"
        rows.append(m)
    print(show(rows))

    print("\n=== B. 多空对称组合")
    rows = []
    Wboth = Wl + Ws
    for A in (1, 2, 3):
        m, *_ = lev.simulate(Wboth, A, *args, **kw)
        m["cfg"] = f"多空对称 {A}x"
        rows.append(m)
    print(show(rows))

    print("\n=== C. 空头门槛更严（空头需要更强信号）")
    rows = []
    for se in (0.3, 0.5, 0.8, 1.2):
        Wsx = lev.signal_weight(z[sym], vol[sym], enter=se, target_vol=0.40, allow_short=True) - \
              lev.signal_weight(z[sym], vol[sym], enter=se, target_vol=0.40, allow_short=False)
        Wc = Wl + Wsx
        m, *_ = lev.simulate(Wc, 2, *args, **kw)
        m["cfg"] = f"空头入场 z<-{se}"
        rows.append(m)
    print(show(rows))

    print("\n=== D. 只在高资金费时做空（收资金费为主）")
    rows = []
    for th in (0.00005, 0.0001, 0.0002, 0.0003):
        gate = (F["BTCUSDT"] > th).astype(float)
        Wg = Wl + Ws.mul(gate, axis=0)
        m, *_ = lev.simulate(Wg, 2, *args, **kw)
        m["cfg"] = f"资金费>{th*1e4:.0f}bp 才做空 ({gate.mean()*100:.0f}%天数)"
        rows.append(m)
    print(show(rows))

    print("\n=== E. 分年（2x 多空对称 vs 只做多）")
    m1, eq1, r1, _ = lev.simulate(Wl, 2, *args, **kw)
    m2, eq2, r2, _ = lev.simulate(Wboth, 2, *args, **kw)
    yr = pd.DataFrame({
        "只做多": ((1 + r1).groupby(r1.index.year).prod() - 1) * 100,
        "多空": ((1 + r2).groupby(r2.index.year).prod() - 1) * 100,
        "BTC": ((1 + C["BTCUSDT"].pct_change().loc[r1.index]).groupby(r1.index.year).prod() - 1) * 100,
    })
    print(yr.round(1).to_string())


if __name__ == "__main__":
    main()
