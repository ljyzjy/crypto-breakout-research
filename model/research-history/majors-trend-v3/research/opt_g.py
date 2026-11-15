"""D vs C: is the entry floor a real edge or just less exposure?

1) floor grid (plateau check)
2) rescale C to D's realised vol -> if D still wins, it is not merely de-risking
3) paired block bootstrap of the daily return difference
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
zc = z[["BTCUSDT"]]


def w_floor(floor, tv=0.40, vol=vol30, cap=1.0):
    s = (tv / vol).clip(upper=1.0)
    return ((zc["BTCUSDT"] - floor).clip(lower=0, upper=cap) * s).fillna(0.0).to_frame("BTCUSDT")


print("=== 入场门槛（2018-2026, 30d vol, 目标40%）===")
rows = []
for f in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
    m, eq, ret = opt.run(w_floor(f), O)
    m["cfg"] = f"floor {f:.1f}"
    m["_ret"] = ret
    rows.append(m)
print(opt.table(rows))
print()
print(opt.ytab(rows))

print("\n=== 门槛 × 波动窗口 ===")
rows2 = []
for f in (0.2, 0.3, 0.4):
    for vn, v in (("30d", vol30), ("60d", vol60)):
        for tv in (0.35, 0.40, 0.45):
            m, _, _ = opt.run(w_floor(f, tv, v), O)
            m["cfg"] = f"floor{f:.1f} {vn} tv{tv:.0%}"
            print(f"   {m['cfg']:<22} cagr {m['cagr']*100:5.1f}%  sharpe {m['sharpe']:5.2f}  "
                  f"mdd {m['mdd']*100:6.1f}%  calmar {m['calmar']:4.2f}  expo {m['expo']*100:4.1f}%")

# ---- 同风险对比
print("\n=== 同风险对比：把 floor0 缩放到 floor0.3 的波动 ===")
Wc = w_floor(0.0)
Wd = w_floor(0.3)
_, _, rc = opt.run(Wc, O)
_, _, rd = opt.run(Wd, O)
print(f"   未缩放: floor0 vol {rc.std()*np.sqrt(365)*100:.1f}%  floor0.3 vol {rd.std()*np.sqrt(365)*100:.1f}%")
k = rd.std() / rc.std()
m, _, _ = opt.run(Wc * k, O)
print(f"   floor0 × {k:.3f}: cagr {m['cagr']*100:5.1f}%  sharpe {m['sharpe']:5.2f}  mdd {m['mdd']*100:6.1f}%  calmar {m['calmar']:4.2f}")

# ---- 配对块自助
print("\n=== 配对自助（20日块，5000次，D-C 日收益差）===")
diff = (rd - rc).dropna()
n = len(diff)
blk = 20
nb = int(np.ceil(n / blk))
rng = np.random.default_rng(7)
sharpe_d = []
for _ in range(5000):
    idx = rng.integers(0, nb, nb)
    parts = [diff.iloc[i * blk:(i + 1) * blk].to_numpy() for i in idx]
    s = np.concatenate(parts)[:n]
    if s.std() > 0:
        sharpe_d.append(s.mean() / s.std() * np.sqrt(365))
sharpe_d = np.array(sharpe_d)
print(f"   差值年化Sharpe: 点估计 {diff.mean()/diff.std()*np.sqrt(365):.2f}  "
      f"5% {np.percentile(sharpe_d,5):.2f}  50% {np.percentile(sharpe_d,50):.2f}  "
      f"95% {np.percentile(sharpe_d,95):.2f}  P(<0) {np.mean(sharpe_d<0)*100:.0f}%")
