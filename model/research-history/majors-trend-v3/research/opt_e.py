"""Is the drawdown governor real, or fitted to 2018/2022?

Checks: threshold x window plateau, per-year contribution, and whether it still helps
when the sample is split in half.
"""
import numpy as np
import pandas as pd

import lab
import opt

C, O, H, L = opt.load_long()
c = C["BTCUSDT"]
r = c.pct_change()
vol30 = r.rolling(30).std() * np.sqrt(365)
vol60 = r.rolling(60).std() * np.sqrt(365)
z = lab.zscore(C, (20, 40, 60, 90))

wB = opt.w_v2(z[["BTCUSDT"]], vol30.to_frame("BTCUSDT"), 0.40)


def governor(win, thr, cut, confirm=3):
    dd = c / c.rolling(win).max() - 1
    f = pd.Series(1.0, index=c.index)
    f[dd < thr] = cut
    return f.rolling(confirm).min()


print("=== 回撤减速：窗口 × 阈值 × 减速幅度（2018-2026, 10bp）===")
rows = []
for win in (30, 60, 120, 250):
    for thr in (-0.12, -0.18, -0.25, -0.32):
        for cut in (0.5, 0.7):
            W = wB.mul(governor(win, thr, cut), axis=0)
            m, eq, ret = opt.run(W, O)
            m["cfg"] = f"win{win:3d} thr{thr:+.0%} x{cut:.1f}"
            m["_ret"] = ret
            rows.append(m)
d = pd.DataFrame([{k: v for k, v in x.items() if not k.startswith("_")} for x in rows])
d["cagr"] = (d.cagr * 100).round(1); d["mdd"] = (d.mdd * 100).round(1); d["vol"] = (d.vol * 100).round(1)
d["sharpe"] = d.sharpe.round(2); d["calmar"] = d.calmar.round(2)
d["expo"] = (d.expo * 100).round(1)
print(d[["cfg", "cagr", "sharpe", "mdd", "calmar", "vol", "expo"]].to_string(index=False))

base = opt.row("基线", wB, O)
best = max(rows, key=lambda x: x["calmar"])
print(f"\n基线 Calmar {base['calmar']:.2f} | 网格中位 Calmar {d.calmar.median():.2f} | 最好 {best['cfg']} {best['calmar']:.2f}")

print("\n=== 分年对比（基线 vs 最优减速）===")
print(pd.DataFrame({"基线": lab.yearly(base["_ret"]).round(1),
                    best["cfg"]: lab.yearly(best["_ret"]).round(1)}).to_string())

print("\n=== 分半样本 ===")
for a, b, lab_ in (("2018-01-01", "2022-06-30", "前半"), ("2022-07-01", "2026-10-31", "后半")):
    m0, _, _ = opt.run(wB, O, start=a, end=b)
    Wb = wB.mul(governor(60, -0.18, 0.5), axis=0)
    m1, _, _ = opt.run(Wb, O, start=a, end=b)
    print(f"{lab_}: 基线 {m0['cagr']*100:5.1f}% / {m0['mdd']*100:5.1f}% / {m0['sharpe']:.2f}   "
          f"减速 {m1['cagr']*100:5.1f}% / {m1['mdd']*100:5.1f}% / {m1['sharpe']:.2f}")
