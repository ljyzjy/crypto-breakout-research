"""Is the |z| spread real, or four lucky days?

The bucket table says strong signals earn 10x the daily edge of weak ones. Before that
becomes a leverage schedule it has to survive: halves, years, medians instead of means,
removing the best days, and a hit-rate/payoff decomposition. Trend systems earn from a
handful of days; if that is all this is, then "conviction" is really "tail dependence"
and levering into it is levering into the tail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)

F = pd.read_parquet("out/conv_frame.parquet")
ok = F["ok"].fillna(False).to_numpy()
h = F["hit"].to_numpy()
z = F["z_abs"].to_numpy()
vol = F["vol"].to_numpy()
er = F["er"].to_numpy()
idx = F.index

d = pd.DataFrame({"hit": h, "z": z, "vol": vol, "er": er}, index=idx)[ok]
d = d.dropna()
d["q"] = pd.qcut(d["z"].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])

print(f"有仓且维度齐全 {len(d)} 天  {d.index[0].date()} -> {d.index[-1].date()}")

print("\n" + "=" * 104)
print("A. |z| 五等分：均值之外的全部诊断（单位 bp，胜率 %）")
print("=" * 104)


def diag(s):
    win = s[s > 0]
    los = s[s < 0]
    return pd.Series({
        "n": len(s),
        "均值": s.mean() * 1e4,
        "中位": s.median() * 1e4,
        "胜率": (s > 0).mean() * 100,
        "平均盈": win.mean() * 1e4 if len(win) else np.nan,
        "平均亏": los.mean() * 1e4 if len(los) else np.nan,
        "盈亏比": (win.mean() / abs(los.mean())) if len(los) and len(win) else np.nan,
        "标准差": s.std() * 1e4,
        "去最好1%": s.sort_values().iloc[:-max(1, len(s) // 100)].mean() * 1e4,
        "去最好5天": s.sort_values().iloc[:-5].mean() * 1e4,
    })


g = d.groupby("q", observed=True)["hit"].apply(diag).unstack()
print(g.round(2).to_string())

print("\n" + "=" * 104)
print("B. 分半样本：单调性是否在两段里都成立")
print("=" * 104)
for name, sub in (("2020-01 ~ 2023-03", d.loc[:"2023-03-31"]),
                  ("2023-04 ~ 2026-10", d.loc["2023-04-01":])):
    gg = sub.groupby("q", observed=True)["hit"].agg(
        n="size", 均值=lambda s: s.mean() * 1e4, 中位=lambda s: s.median() * 1e4,
        胜率=lambda s: (s > 0).mean() * 100,
        shp=lambda s: s.mean() / s.std() * np.sqrt(365))
    print(f"\n--- {name}  ({len(sub)} 天)")
    print(gg.round(2).to_string())

print("\n" + "=" * 104)
print("C. 逐年：Q5-Q1 的均值差（bp/日）")
print("=" * 104)
yr = d.groupby([d.index.year, "q"], observed=True)["hit"].mean().unstack() * 1e4
yr["Q5-Q1"] = yr["Q5"] - yr["Q1"]
yr["天数"] = d.groupby(d.index.year).size()
print(yr.round(1).to_string())

print("\n" + "=" * 104)
print("D. 收益集中度：整条方向收益的利润来自多少天？")
print("=" * 104)
s = d["hit"].sort_values(ascending=False)
tot = s.sum()
for k in (5, 10, 20, 50, 100):
    print(f"  最好的 {k:3d} 天（{k/len(s)*100:4.1f}%）贡献了总利润的 "
          f"{s.iloc[:k].sum()/tot*100:6.1f}%")
print(f"  去掉最好 1% 后总利润变化: {(tot - s.iloc[:15].sum())/tot*100:.1f}% 剩余")
print(f"  正收益天数 {int((s>0).sum())}，负收益天数 {int((s<0).sum())}")

print("\n  各 |z| 桶里，最好 3 天贡献占该桶总利润的比例：")
for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
    ss = d.loc[d["q"] == q, "hit"].sort_values(ascending=False)
    if ss.sum() > 0:
        print(f"    {q}: 最好3天 {ss.iloc[:3].sum()/ss.sum()*100:6.1f}%   "
              f"桶总利润 {ss.sum()*1e4:8.0f}bp   n={len(ss)}")

print("\n" + "=" * 104)
print("E. 波动率五等分（复核 lev_g 的「低波是亏损桶」）")
print("=" * 104)
d["vq"] = pd.qcut(d["vol"].rank(method="first"), 5, labels=["v1低", "v2", "v3", "v4", "v5高"])
gv = d.groupby("vq", observed=True)["hit"].apply(diag).unstack()
print(gv.round(2).to_string())

print("\n" + "=" * 104)
print("F. 强信号但 ER 低的子样本 = lev_g 里的「陷阱」？")
print("=" * 104)
for nm, m in (("z>1 且 ER>0.30", (d["z"] > 1.0) & (d["er"] > 0.30)),
              ("z>1 且 ER<0.20", (d["z"] > 1.0) & (d["er"] < 0.20)),
              ("z<0.6（弱信号）", d["z"] < 0.6),
              ("z>1.3（强信号）", d["z"] > 1.3)):
    sub = d.loc[m, "hit"]
    print(f"  {nm:<18} n={len(sub):4d}  均值 {sub.mean()*1e4:+7.1f}bp  "
          f"胜率 {(sub>0).mean()*100:5.1f}%  Sharpe {sub.mean()/sub.std()*np.sqrt(365):5.2f}  "
          f"去最好3天 {sub.sort_values().iloc[:-3].mean()*1e4:+7.1f}bp")

print("\n" + "=" * 104)
print("G. 关键算术：把杠杆倾斜到强信号，等于把仓位对信号变成平方")
print("=" * 104)
print("  当前: w = clip(z,0,1) * min(1, 0.4/vol)      -> 对 z 线性")
print("  倾斜: w = clip(z,0,1) * min(1,0.4/vol) * A(z) -> 若 A 也随 z 升，对 z 超线性")
for zt in (0.3, 0.6, 1.0):
    for at in (1.0, 1.5, 2.0, 3.0):
        print(f"    z={zt:.1f}  A={at:.1f}x  ->  实际名义 {zt*at:.2f}x 权益"
              + ("  <-- 已超出 z=1,A=3 的 3x" if zt * at > 3 else ""))
    print()
