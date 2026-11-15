"""The real lesson from the breakout project: models learn volatility, not direction.

Every table in that project shows precision rising while forward return stays negative
and the hit rate stays pinned near 45%. That is the signature of a model that predicts
*how much* price will move but not *which way*. This tests it directly on its own 920k
bars: same features, two labels -- "will the next bar be big" vs "will the next bar be
up" -- and compares the AUC. Volatility is autocorrelated and forecastable; direction,
if the AUC lands on 0.50, is not.

Second part uses the full 2500-day daily sample for the question the 15m data cannot
answer: is the 00:00 open a systematically bad fill for a trend signal?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

pd.set_option("display.width", 240)
SRC = r"C:\Users\WIN11\Documents\Codex\2026-11-13\c-users-win11-documents-codex-2026-2\work\breakout_analysis\allbars.parquet"


def auc(x, y):
    """Mann-Whitney AUC. y is 0/1."""
    x = np.asarray(x, float)
    y = np.asarray(y, bool)
    n1 = int(y.sum())
    n0 = int((~y).sum())
    if n1 == 0 or n0 == 0:
        return np.nan
    r = pd.Series(x).rank().to_numpy()
    return (r[y].sum() - n1 * (n1 + 1) / 2) / (n0 * n1)


def part_a():
    cols = ["ts", "symbol", "section", "body", "ret1", "ret4", "position",
            "volratio", "activity"]
    d = pd.read_parquet(SRC, columns=cols)
    d = d.sort_values(["symbol", "ts"])
    d["fut"] = d.groupby("symbol")["body"].shift(-1)
    d = d.dropna(subset=["fut", "ret1", "ret4", "position", "volratio", "activity"])
    d["dt"] = pd.to_datetime(d["ts"], unit="ms", utc=True)

    y_vol = (d["fut"].abs() >= 0.01).to_numpy()
    y_dir = (d["fut"] > 0).to_numpy()
    print(f"样本 {len(d)} 根柱   {d['dt'].min().date()} -> {d['dt'].max().date()}")
    print(f"「下一根是大柱」基准率 {y_vol.mean()*100:.2f}%   "
          f"「下一根是阳线」基准率 {y_dir.mean()*100:.2f}%")

    # time split, so nothing is fitted and scored on the same period
    cut = d["dt"].quantile(0.5)
    tr = (d["dt"] <= cut).to_numpy()
    te = ~tr

    feats = ["ret1", "ret4", "position", "volratio", "activity"]
    print("\n" + "=" * 100)
    print("A. 同一批特征，两个标签的 AUC（前半训练期 / 后半检验期）")
    print("   波动标签：下一根柱 |实体| >= 1%      方向标签：下一根柱是阳线")
    print("=" * 100)
    print(f"{'特征':<12}{'波动AUC(前)':>12}{'波动AUC(后)':>12}{'':>4}"
          f"{'方向AUC(前)':>12}{'方向AUC(后)':>12}")
    rows = []
    for f in feats:
        v1 = auc(d.loc[tr, f], y_vol[tr])
        v2 = auc(d.loc[te, f], y_vol[te])
        d1 = auc(d.loc[tr, f], y_dir[tr])
        d2 = auc(d.loc[te, f], y_dir[te])
        print(f"{f:<12}{v1:>12.4f}{v2:>12.4f}{'':>4}{d1:>12.4f}{d2:>12.4f}")
        rows.append((f, v1, v2, d1, d2))

    print("\n" + "=" * 100)
    print("B. 组合特征（等权排名求和）：波动能不能测、方向能不能测")
    print("=" * 100)

    def combo(frame, flip=()):
        s = pd.Series(0.0, index=frame.index)
        for f in feats:
            r = frame[f].rank(pct=True)
            s = s + (1 - r if f in flip else r)
        return s.to_numpy()

    cv1 = auc(combo(d[tr]), y_vol[tr])
    cv2 = auc(combo(d[te]), y_vol[te])
    cd1 = auc(combo(d[tr]), y_dir[tr])
    cd2 = auc(combo(d[te]), y_dir[te])
    print(f"  组合 -> 波动 : 前 {cv1:.4f}   后 {cv2:.4f}")
    print(f"  组合 -> 方向 : 前 {cd1:.4f}   后 {cd2:.4f}")
    print("\n  解读：波动 AUC 明显高于 0.5 = 波动率有自相关，可预测；")
    print("        方向 AUC 贴近 0.5 = 方向不可预测。这就是精确率涨、收益不涨的原因。")

    print("\n" + "=" * 100)
    print("C. 按天分 10 段：方向 AUC 是否稳定在 0.50 附近（检验不是某段特例）")
    print("=" * 100)
    d["seg"] = pd.qcut(d["dt"].astype("int64"), 10, labels=False)
    out = []
    for g, sub in d.groupby("seg"):
        m = sub.index
        out.append(dict(段=int(g), n=len(sub),
                        vol_auc=auc(sub["volratio"], (sub["fut"].abs() >= 0.01)),
                        dir_auc=auc(sub["ret1"], sub["fut"] > 0)))
    t = pd.DataFrame(out)
    print(t.round(4).to_string(index=False))
    print(f"\n  波动AUC 均值 {t['vol_auc'].mean():.4f}  (min {t['vol_auc'].min():.4f})")
    print(f"  方向AUC 均值 {t['dir_auc'].mean():.4f}  (min {t['dir_auc'].min():.4f}, "
          f"max {t['dir_auc'].max():.4f})")


def part_d():
    """Full daily sample: is the open a bad fill? Measured as the gap against the signal."""
    import lev
    from lev_a import prep
    from lev_f import final_rules

    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    f = F["BTCUSDT"]
    W, *_ = final_rules(C[sym], vol[sym], z[sym], f)
    Wd = W["BTCUSDT"].shift(1).fillna(0.0)
    act = Wd.abs() > 1e-9
    dirn = np.sign(Wd)

    gap = (O["BTCUSDT"] / C["BTCUSDT"].shift(1) - 1.0)
    aligned = (dirn * gap)[act].dropna() * 1e4

    print("\n" + "=" * 100)
    print("D. 日线全样本（2020-2026, 1490 个有仓日）：开盘相对前收盘的同向跳空")
    print("   正 = 趋势日高开（开盘追高），负 = 趋势日低开（开盘是折扣价）")
    print("=" * 100)
    print(f"  n={len(aligned)}  均值 {aligned.mean():+.2f}bp  中位 {aligned.median():+.2f}bp  "
          f"胜率 {(aligned>0).mean()*100:.1f}%  "
          f"t={aligned.mean()/(aligned.std()/np.sqrt(len(aligned))):.2f}")
    h1 = aligned.loc[:"2023-03-31"]
    h2 = aligned.loc["2023-04-01":]
    print(f"  前半 {h1.mean():+.2f}bp (n={len(h1)})   后半 {h2.mean():+.2f}bp (n={len(h2)})")
    yr = aligned.groupby(aligned.index.year).agg(["size", "mean"])
    print("\n  逐年：")
    print(yr.round(2).to_string())
    print(f"\n  年化影响（若把跳空完全避开）: {aligned.mean()*365/100:+.2f}%")
    print("  注：跳空不可避开 —— 它发生在开盘那一刻，无法用限价单吃到。")


if __name__ == "__main__":
    part_a()
    part_d()
