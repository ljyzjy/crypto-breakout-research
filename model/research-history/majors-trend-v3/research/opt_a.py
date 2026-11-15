import numpy as np
import pandas as pd

import lab
import opt

C, O, H, L = opt.load_long()
BTC = ["BTCUSDT"]
c, o = C[BTC], O[BTC]

r = c.pct_change()
vol30 = r.rolling(30).std() * np.sqrt(365)
vol60 = r.rolling(60).std() * np.sqrt(365)
vol_ewma = r.ewm(span=30, min_periods=20).std() * np.sqrt(365)

print("样本", C.index[0].date(), "->", C.index[-1].date(), "| BTC 天数", len(C))

rows = []
z_base = lab.zscore(c, (20, 40, 60, 90))

# ---- A. reproduce V2 baseline
rows.append(opt.row("V2 基线 (30d vol, 40%)", opt.w_v2(z_base, vol30, 0.40), o))

# ---- B. lookback sets
for lbs in [(10, 20, 40), (20, 40, 60, 90), (20, 40, 60, 90, 120), (40, 80, 120, 180),
            (20, 60, 120, 250), (60, 120, 250)]:
    rows.append(opt.row(f"回看 {lbs}", opt.w_v2(lab.zscore(c, lbs), vol30, 0.40), o))

print("\n=== 回看窗口 ===")
print(opt.table(rows))
print(opt.ytab(rows))

# ---- C. vol estimator
rows2 = []
for name, v in [("30d", vol30), ("60d", vol60), ("EWMA30", vol_ewma), ("max(30d,60d)", np.maximum(vol30, vol60))]:
    rows2.append(opt.row(f"vol={name}", opt.w_v2(z_base, v, 0.40), o))
print("\n=== 波动率估计 ===")
print(opt.table(rows2))
print(opt.ytab(rows2))

# ---- D. sizing map
rows3 = []
for tv in (0.25, 0.30, 0.40, 0.50, 0.60, 0.80):
    rows3.append(opt.row(f"线性 目标{tv:.0%}", opt.w_v2(z_base, vol30, tv), o))
for tv in (0.40, 0.50, 0.60):
    rows3.append(opt.row(f"tanh 目标{tv:.0%}", opt.w_tanh(z_base, vol30, tv, k=1.5), o))
    rows3.append(opt.row(f"sqrt 目标{tv:.0%}", opt.w_sqrt(z_base, vol30, tv), o))
print("\n=== 仓位映射 ===")
print(opt.table(rows3))
