"""Liquidation arithmetic on daily OHLC, no extra data needed.

Isolated margin on Binance USDⓈ-M: at leverage L a position locks 1/L of notional as
margin and is force-closed once its loss reaches (1/L - mm) of notional. The liquidation
distance in price terms is therefore d = 1/L - mm, **independent of position size**.

So "40x" does not mean "40x the risk you wanted" -- it means "a 2.1% adverse move ends
the trade". The question is whether the signal's holding periods ever move that far.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab
import opt

MM = 0.004     # BTCUSDT perp tier-1 maintenance margin rate


def liq_dist(lev: float, mm: float = MM) -> float:
    return 1.0 / lev - mm


def build_blocks(z, C):
    vol = C.pct_change().rolling(60).std() * np.sqrt(365)
    w = (z.clip(lower=0, upper=1.0) * (0.40 / vol).clip(upper=1.0)).fillna(0.0)
    w = w.where(z > 0.20, 0.0)
    on = (w > 0).to_numpy()
    idx = w.index
    blocks, start = [], None
    for i, flag in enumerate(on):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            blocks.append((idx[start], idx[i]))
            start = None
    if start is not None:
        blocks.append((idx[start], idx[-1]))
    return blocks


def main():
    C, O, H, Lo = opt.load_long(("BTCUSDT",))
    C, O, H, Lo = C["BTCUSDT"], O["BTCUSDT"], H["BTCUSDT"], Lo["BTCUSDT"]
    df = pd.DataFrame({"o": O, "h": H, "l": Lo, "c": C}).dropna().loc["2019-09-01":]

    dn = df["l"] / df["o"] - 1.0
    up = df["h"] / df["o"] - 1.0
    print(f"样本 {len(df)} 天  {df.index[0].date()} -> {df.index[-1].date()}")
    print(f"日内不利偏移(从开盘): 多头 中位 {dn.median()*100:.2f}%  最差 {dn.min()*100:.1f}%")
    print(f"                      空头 中位 {up.median()*100:.2f}%  最差 {up.max()*100:.1f}%\n")

    rows = []
    for lev in (1, 2, 3, 5, 10, 20, 40):
        d = liq_dist(lev)
        p_long = float((dn <= -d).mean())
        p_short = float((up >= d).mean())
        rows.append(dict(杠杆=f"{lev}x", 强平距离=f"{d*100:.2f}%",
                         单日多头被扫=f"{p_long*100:.1f}%",
                         单日空头被扫=f"{p_short*100:.1f}%",
                         连挂10天存活=f"{(1-p_long)**10*100:.1f}%"))
    print("== 单日强平概率")
    print(pd.DataFrame(rows).to_string(index=False))

    z = lab.zscore(C.to_frame("BTCUSDT"), (20, 40, 60, 90))["BTCUSDT"]
    blocks = build_blocks(z, C)
    maes = []
    for a, b in blocks:
        seg = df.loc[a:b]
        if len(seg) < 2:
            continue
        maes.append((a, b, len(seg), min(seg["l"].min() / seg["o"].iloc[0] - 1.0, 0.0)))
    m = pd.DataFrame(maes, columns=["start", "end", "days", "mae"])
    print(f"\n== 实际持仓块 {len(m)} 段，中位持有 {m.days.median():.0f} 天")
    qs = [0.50, 0.80, 0.90, 0.95, 1.00]
    vals = [m.mae.quantile(1 - q) for q in qs]
    print("持仓期最大不利偏移: " + "  ".join(f"p{int(q*100)} {v*100:.1f}%" for q, v in zip(qs, vals)))

    print("\n== 每段不被强平所需的最大杠杆 1/(|MAE|+mm)")
    lev_ok = 1.0 / (m.mae.abs() + MM)
    print(f"   中位 {lev_ok.median():.1f}x   p10 {lev_ok.quantile(.1):.1f}x   最小 {lev_ok.min():.1f}x")
    for lev in (1, 2, 3, 5, 10, 20, 40):
        n = int((lev_ok < lev).sum())
        print(f"   {lev:>2}x: {n:2d}/{len(m)} 段被强平 ({n/len(m)*100:3.0f}%)")

    m.assign(mae_pct=(m.mae * 100).round(1),
             start=m.start.dt.date, end=m.end.dt.date).to_csv("out/mae_blocks.csv", index=False)
    print("\n明细前12段:")
    print(m.head(12).assign(mae=(m.mae * 100).round(1), start=m.start.dt.date,
                            end=m.end.dt.date).to_string(index=False))


if __name__ == "__main__":
    main()
