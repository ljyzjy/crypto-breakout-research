import numpy as np
import pandas as pd

import lab
import opt

C, O, H, L = opt.load_long()
r = C.pct_change()
vol30 = r.rolling(30).std() * np.sqrt(365)
z = lab.zscore(C, (20, 40, 60, 90))

print("样本", C.index[0].date(), "->", C.index[-1].date())

rows = []
wB = opt.w_v2(z[["BTCUSDT"]], vol30[["BTCUSDT"]], 0.40)
wE = opt.w_v2(z[["ETHUSDT"]], vol30[["ETHUSDT"]], 0.40)
rows.append(opt.row("BTC 单币 (基线)", wB, O))

# ---- A. 双币独立信号，按资金比例合成
for a in (0.9, 0.8, 0.7, 0.6, 0.5):
    W = pd.concat([wB["BTCUSDT"] * a, wE["ETHUSDT"] * (1 - a)], axis=1)
    rows.append(opt.row(f"BTC{a:.0%}+ETH{1-a:.0%}", W, O))

# ---- B. 只用闲置资金做 ETH（BTC 有仓时不加 ETH）
Wc = pd.concat([wB["BTCUSDT"], (wE["ETHUSDT"] * (1 - wB["BTCUSDT"])).clip(lower=0)], axis=1)
rows.append(opt.row("BTC 优先 + ETH 填空", Wc, O))

# ---- C. 双币取强者（相对动量）
rel = (z["BTCUSDT"] - z["ETHUSDT"])
Wr = pd.concat([wB["BTCUSDT"] * (rel > 0), wE["ETHUSDT"] * (rel <= 0)], axis=1)
rows.append(opt.row("BTC/ETH 择强", Wr, O))

print("\n=== 增加第二个标的 ===")
print(opt.table(rows))
print(opt.ytab(rows))

# ---- D. 回撤减速：距 60 日高点回撤超阈值时减半
rows2 = []
for thr, cut in [(-0.15, 0.5), (-0.20, 0.5), (-0.25, 0.5), (-0.20, 0.0), (-0.25, 0.0)]:
    dd = C["BTCUSDT"] / C["BTCUSDT"].rolling(60).max() - 1
    f = pd.Series(1.0, index=C.index)
    f[dd < thr] = cut
    # 平滑：连续 3 天满足才降档，避免噪声
    f = f.rolling(3).min()
    rows2.append(opt.row(f"回撤{thr:.0%}→×{cut:.1f}", wB.mul(f, axis=0), O))

# ---- E. 波动突增减速
med = vol30["BTCUSDT"].rolling(250).median()
for k, cut in [(1.8, 0.5), (2.2, 0.5), (2.2, 0.0)]:
    f = pd.Series(1.0, index=C.index)
    f[vol30["BTCUSDT"] > k * med] = cut
    f = f.rolling(3).min()
    rows2.append(opt.row(f"vol>{k}×中位→×{cut:.1f}", wB.mul(f, axis=0), O))

print("\n=== 熊市/动荡减速 ===")
print(opt.table(rows2))
print(opt.ytab(rows2))
