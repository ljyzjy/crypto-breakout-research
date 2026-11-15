"""The honesty test: does z add anything over a constant vol-targeted BTC position?

Control A: always long, sized only by the vol budget (pure risk-managed beta).
Control B: binary z>0 switch, same vol budget.
V2:        continuous clip(z,0,1).

If V2 does not beat A, the whole signal layer is decoration.
"""
import numpy as np
import pandas as pd

import lab
import opt

C, O, H, L = opt.load_long()
c = C["BTCUSDT"]
r = c.pct_change()
vol30 = r.rolling(30).std() * np.sqrt(365)
z = lab.zscore(C, (20, 40, 60, 90))
zc = z[["BTCUSDT"]]

scale = (0.40 / vol30).clip(upper=1.0)

variants = {
    "A 永远满仓(仅风险预算)": scale.fillna(0.0).to_frame("BTCUSDT"),
    "B 二元 z>0": (scale * (zc["BTCUSDT"] > 0)).fillna(0.0).to_frame("BTCUSDT"),
    "C V2 线性 clip(z,0,1)": opt.w_v2(zc, vol30.to_frame("BTCUSDT"), 0.40),
    "D 线性门槛 z>0.3": (scale * (zc["BTCUSDT"] - 0.3).clip(lower=0, upper=1)).fillna(0.0).to_frame("BTCUSDT"),
    "E 纯多头 BTC 日线": pd.DataFrame(1.0, index=c.index, columns=["BTCUSDT"]),
}

rows = []
for name, W in variants.items():
    m, eq, ret = opt.run(W, O)
    m["cfg"] = name
    m["_ret"] = ret
    rows.append(m)
print("=== 2018-2026 ===")
print(opt.table(rows))
print()
print(opt.ytab(rows))

print("\n=== 分半 ===")
for a, b, lab_ in (("2018-01-01", "2022-06-30", "前半"), ("2022-07-01", "2026-10-31", "后半")):
    print(f"-- {lab_}")
    for name, W in variants.items():
        m, _, _ = opt.run(W, O, start=a, end=b)
        print(f"   {name:<24} cagr {m['cagr']*100:6.1f}%  sharpe {m['sharpe']:5.2f}  mdd {m['mdd']*100:6.1f}%")

# ---- 杠杆：波动缩放允许超过 1（现货做不到，需要永续/杠杆）
print("\n=== 允许反向波动加杠杆（需要永续，非现货）===")
for lev in (1.0, 1.5, 2.0, 2.5):
    s = (0.40 / vol30).clip(upper=lev)
    W = (zc["BTCUSDT"].clip(lower=0, upper=1) * s).clip(upper=lev).fillna(0.0).to_frame("BTCUSDT")
    m, _, _ = opt.run(W, O)
    print(f"   上限 {lev:.1f}x  cagr {m['cagr']*100:6.1f}%  sharpe {m['sharpe']:5.2f}  mdd {m['mdd']*100:6.1f}%  "
          f"calmar {m['calmar']:4.2f}  expo {m['expo']*100:5.1f}%")
