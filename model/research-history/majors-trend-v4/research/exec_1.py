"""Execution timing on 15m bars: is the daily open the worst possible fill?

The breakout project measured 15-minute breakouts and found forward returns of -0.05%
with a 45% hit rate -- short horizons mean-revert. If that is structural, the daily
strategy's habit of filling at the 00:00 open may be buying the local extreme every
time. This measures, on the same signal, what the rest of the day does after the open.

Sample is 2025-07-01..2026-11-12 (BTCUSDT, complete 15m grid), which is also the most
recent out-of-sample window for the daily model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

pd.set_option("display.width", 240)
SRC = r"C:\Users\WIN11\Documents\Codex\2026-11-13\c-users-win11-documents-codex-2026-2\work\breakout_analysis\allbars.parquet"


def daily_from_15m(sym="BTCUSDT"):
    b = pd.read_parquet(SRC, columns=["ts", "symbol", "open", "high", "low", "close"])
    b = b[b["symbol"] == sym].copy()
    b["dt"] = pd.to_datetime(b["ts"], unit="ms", utc=True)
    b = b.set_index("dt").sort_index()
    d = b.resample("1D").agg(open=("open", "first"), high=("high", "max"),
                             low=("low", "min"), close=("close", "last"))
    d["n"] = b["close"].resample("1D").size()
    d = d[d["n"] >= 90]                       # drop partial days
    return b, d


def daily_signal(d, target_vol=0.40, enter=0.20):
    C = d["close"]
    r = C.pct_change()
    parts = []
    for n in (20, 40, 60, 90):
        v = r.rolling(n).std() * np.sqrt(n)
        parts.append(((C / C.shift(n) - 1) / v.replace(0, np.nan)).clip(-3, 3))
    z = sum(parts) / len(parts)
    vol = (r.rolling(60).std() * np.sqrt(365)).clip(lower=0.05)
    scale = (target_vol / vol).clip(upper=1.0)
    w = (z.clip(lower=0, upper=1.0) * scale).where(z > enter, 0.0).fillna(0.0)
    zs = -z
    ws = (-zs).clip(lower=0, upper=1.0) * scale
    ws = ws.where(zs > enter, 0.0).fillna(0.0)
    return z, vol, w - ws


def main():
    b, d = daily_from_15m()
    print(f"15m 柱 {len(b)} 根，日线 {len(d)} 天  {d.index[0].date()} -> {d.index[-1].date()}")

    z, vol, W = daily_signal(d)
    Wd = W.shift(1).fillna(0.0)                 # weight held on day t (signal from t-1)
    dirn = np.sign(Wd)
    act = Wd.abs() > 1e-9
    print(f"有仓天数 {int(act.sum())}（{act.mean()*100:.0f}%）"
          f"   多 {int((Wd>0).sum())} 天 / 空 {int((Wd<0).sum())} 天")

    # ---- intraday curve: price at each slot relative to the day's open
    # index by bar number within the day (k), not clock time: 96 bars, k=0 covers 00:00-00:15
    b = b.reset_index()
    b["day"] = b["dt"].dt.normalize()
    b["k"] = b.groupby("day").cumcount()
    grid = b.pivot_table(index="day", columns="k", values="close")
    grid = grid.reindex(d.index)
    slots = {0: "00:15", 1: "00:30", 3: "01:00", 7: "02:00", 11: "03:00",
             15: "04:00", 23: "06:00", 31: "08:00", 39: "10:00", 47: "12:00",
             63: "16:00", 79: "20:00", 95: "23:45"}
    px = pd.DataFrame({lbl: grid[k] for k, lbl in slots.items() if k in grid.columns})
    px.index = d.index
    open_ = d["open"]
    close_ = d["close"]
    print(f"可用日内快照 {px.shape[1]} 个时点，覆盖 {px.notna().all(axis=1).sum()} 天")

    print("\n" + "=" * 104)
    print("A. 开盘之后到各时点，价格相对开盘的同向变化（乘信号方向，bp）")
    print("   负数 = 开盘后逆行 → 晚进场更好；正数 = 开盘后顺行 → 早进场更好")
    print("=" * 104)
    rows = []
    for s in px.columns:
        mv = (dirn * (px[s] / open_ - 1.0))[act].dropna() * 1e4
        h1 = mv.loc[:"2026-02-28"]
        h2 = mv.loc["2026-03-01":]
        rows.append(dict(时点=s, n=len(mv), 均值=mv.mean(), 中位=mv.median(),
                         胜率=(mv > 0).mean() * 100, t=mv.mean() / (mv.std() / np.sqrt(len(mv))),
                         前半=h1.mean(), 后半=h2.mean()))
    print(pd.DataFrame(rows).round(1).to_string(index=False))

    print("\n" + "=" * 104)
    print("B. 若改为在该时点进场，全天收益相对「开盘进场」的差（bp/日）")
    print("   等价于 -A 列；同时给出对应的年化影响")
    print("=" * 104)
    rows = []
    for s in px.columns:
        mv = (dirn * (px[s] / open_ - 1.0))[act].dropna()
        gain = -mv
        rows.append(dict(时点=s, 每差日=gain.mean() * 1e4,
                         年化影响=gain.mean() * 365 * 100,
                         t=gain.mean() / (gain.std() / np.sqrt(len(gain)))))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n" + "=" * 104)
    print("C. 日内 96 个时段的平均同向收益（找时段效应，UTC）")
    print("=" * 104)
    b2 = b.copy()
    b2["h"] = b2.index.hour
    b2["m"] = b2.index.minute
    b2["ret"] = b2["close"] / b2["open"] - 1.0
    b2["day"] = b2.index.normalize()
    b2["dir"] = dirn.reindex(b2["day"]).to_numpy()
    bb = b2.dropna(subset=["dir"])
    bb = bb[bb["dir"] != 0]
    g = bb.groupby("h")["ret"].apply(lambda s: s.mean() * 1e4)
    gd = bb.assign(r=bb["ret"] * bb["dir"]).groupby("h")["r"].agg(
        n="size", mean=lambda s: s.mean() * 1e4,
        shp=lambda s: s.mean() / s.std() * np.sqrt(96 * 365) if s.std() else np.nan)
    print(gd.round(2).to_string())
    print("\n  按小时分组的最高/最低：")
    print(f"    最好 {gd['mean'].idxmax():02d} 时  {gd['mean'].max():+.1f}bp")
    print(f"    最差 {gd['mean'].idxmin():02d} 时  {gd['mean'].min():+.1f}bp")

    print("\n" + "=" * 104)
    print("D. 分段稳定性：开盘后 15 分钟的同向收益，逐月")
    print("=" * 104)
    mv15 = (dirn * (px["00:15"] / open_ - 1.0))[act].dropna() * 1e4
    m = mv15.groupby([mv15.index.year, mv15.index.month]).agg(["size", "mean"])
    m.index = [f"{y}-{mm:02d}" for y, mm in m.index]
    print(m.round(1).to_string())
    print(f"\n  为正的月份 {int((m['mean']>0).sum())}/{len(m)}，"
          f"平均 {m['mean'].mean():+.1f}bp")


if __name__ == "__main__":
    main()
