"""Leverage ladder on the perp engine: where does more leverage stop helping?

A = notional / equity. Liquidation distance is 1/A - mm, so the ladder is really a
question about how far the signal's adverse excursions run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 220)


def prep(start="2020-01-01"):
    C, O, H, L, F = lev.load_perp()
    C, O, H, L, F = (x.loc[start:] for x in (C, O, H, L, F))
    r = C.pct_change()
    vol = (r.rolling(60).std() * np.sqrt(365)).clip(lower=0.05)
    z = lev.zscore(C, (20, 40, 60, 90))
    return C, O, H, L, F, r, vol, z


def show(rows, cols=("cfg", "cagr", "vol", "sharpe", "mdd", "calmar", "liq", "fee_pa", "fund_pa", "expo")):
    d = pd.DataFrame(rows)
    for c in ("cagr", "vol", "mdd", "fee_pa", "fund_pa", "expo"):
        if c in d:
            d[c] = (d[c] * 100).round(1)
    for c in ("sharpe", "calmar"):
        if c in d:
            d[c] = d[c].round(2)
    return d[list(cols)].to_string(index=False)


def main():
    C, O, H, L, F, r, vol, z = prep()
    print(f"永续样本 {C.index[0].date()} -> {C.index[-1].date()}  {len(C)} 天")
    print("资金费: 多头日均 %.2f bp  年化 %.1f%%" %
          (F["BTCUSDT"].mean() * 1e4, F["BTCUSDT"].mean() * 365 * 100))

    W1 = lev.signal_weight(z[["BTCUSDT"]], vol[["BTCUSDT"]], enter=0.20,
                           target_vol=0.40, allow_short=False)

    print("\n=== A. 固定倍率梯度（多头，含强平与资金费）")
    rows = []
    for A in (1, 1.5, 2, 3, 5, 8, 12, 20, 40):
        m, eq, ret, log = lev.simulate(W1, A, C[["BTCUSDT"]], O[["BTCUSDT"]],
                                      H[["BTCUSDT"]], L[["BTCUSDT"]], F[["BTCUSDT"]],
                                      start="2020-01-01")
        m["cfg"] = f"{A}x"
        m["yrs"] = {2: f"{m['cagr']*100:.0f}%"}.get(0, "")
        rows.append(m)
    print(show(rows))

    print("\n=== B. 无强平（上限参照，说明强平到底吃掉多少）")
    rows = []
    for A in (2, 5, 12, 40):
        m, *_ = lev.simulate(W1, A, C[["BTCUSDT"]], O[["BTCUSDT"]], H[["BTCUSDT"]],
                             L[["BTCUSDT"]], F[["BTCUSDT"]], liq=False, start="2020-01-01")
        m["cfg"] = f"{A}x 无强平"
        rows.append(m)
    print(show(rows))

    print("\n=== C. 波动率条件倍率：A_t = clip(1/(k*sig_H + mm), 1, 40)")
    rows = []
    for H_days in (1, 3, 5, 10):
        for k in (2.0, 2.5, 3.0):
            sigH = vol["BTCUSDT"] * np.sqrt(H_days / 365)
            A = (1.0 / (k * sigH + lev.MM)).clip(1.0, 40.0)
            m, eq, ret, log = lev.simulate(W1, A, C[["BTCUSDT"]], O[["BTCUSDT"]],
                                          H[["BTCUSDT"]], L[["BTCUSDT"]],
                                          F[["BTCUSDT"]], start="2020-01-01")
            m["cfg"] = f"H={H_days}d k={k}  A中位{A.median():.0f}x [{A.min():.0f}-{A.max():.0f}]"
            rows.append(m)
    print(show(rows))

    print("\n=== D. 恒风险：A_t 反比于波动（不看信号，纯 vol targeting）")
    rows = []
    for tv in (0.4, 0.6, 0.8, 1.0):
        A = (tv / vol["BTCUSDT"]).clip(1.0, 40.0)
        m, *_ = lev.simulate(W1, A, C[["BTCUSDT"]], O[["BTCUSDT"]], H[["BTCUSDT"]],
                             L[["BTCUSDT"]], F[["BTCUSDT"]], start="2020-01-01")
        m["cfg"] = f"目标波动 {int(tv*100)}%  A中位{A.median():.0f}x"
        rows.append(m)
    print(show(rows))


if __name__ == "__main__":
    main()
