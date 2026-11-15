"""Final checks on V3 candidate: floor 0.2 + 60d vol + target 40%.

- split sample
- paired block bootstrap of Sharpe(V3) - Sharpe(V2)
- trade-level summary (entries, holding, exposure)
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


def build(floor, tv, vol, cap=1.0):
    s = (tv / vol).clip(upper=1.0)
    return ((zc["BTCUSDT"] - floor).clip(lower=0, upper=cap) * s).fillna(0.0).to_frame("BTCUSDT")


V2 = build(0.0, 0.40, vol30)
V3 = build(0.2, 0.40, vol60)
V3b = build(0.2, 0.35, vol60)

print("=== 分半（2018-01→2022-06 / 2022-07→2026-10）===")
for a, b, lab_ in (("2018-01-01", "2022-06-30", "前半"), ("2022-07-01", "2026-10-31", "后半")):
    print(f"-- {lab_}")
    for nm, W in (("V2 基线", V2), ("V3 floor.2/60d/40%", V3), ("V3b floor.2/60d/35%", V3b)):
        m, _, _ = opt.run(W, O, start=a, end=b)
        print(f"   {nm:<22} cagr {m['cagr']*100:6.1f}%  sharpe {m['sharpe']:5.2f}  mdd {m['mdd']*100:6.1f}%")

print("\n=== 全样本 ===")
res = {}
for nm, W in (("V2", V2), ("V3", V3), ("V3b", V3b)):
    m, eq, ret = opt.run(W, O)
    res[nm] = (m, ret, W)
    print(f"{nm:<4} cagr {m['cagr']*100:5.1f}%  sharpe {m['sharpe']:5.2f}  mdd {m['mdd']*100:6.1f}%  "
          f"calmar {m['calmar']:4.2f}  vol {m['vol']*100:4.1f}%  expo {m['expo']*100:4.1f}%  turn {m['turn']:5.1f}")

# ---- 配对块自助：Sharpe 差值
r2 = res["V2"][1]
r3 = res["V3"][1]
idx = r2.index.intersection(r3.index)
x2, x3 = r2.loc[idx].to_numpy(), r3.loc[idx].to_numpy()
n = len(idx); blk = 20; nb = int(np.ceil(n / blk))
rng = np.random.default_rng(11)
d_sh, d_cagr, d_mdd = [], [], []
for _ in range(4000):
    pick = rng.integers(0, nb, nb)
    sel = np.concatenate([np.arange(i * blk, min((i + 1) * blk, n)) for i in pick])
    a, b = x2[sel], x3[sel]
    if a.std() == 0 or b.std() == 0:
        continue
    d_sh.append(b.mean() / b.std() * np.sqrt(365) - a.mean() / a.std() * np.sqrt(365))
    ea = np.cumprod(1 + a); eb = np.cumprod(1 + b)
    yrs = len(sel) / 365
    d_cagr.append((eb[-1] ** (1 / yrs) - 1) - (ea[-1] ** (1 / yrs) - 1))
    d_mdd.append((eb / np.maximum.accumulate(eb) - 1).min() - (ea / np.maximum.accumulate(ea) - 1).min())

for nm, arr, unit in (("Sharpe 差", d_sh, ""), ("CAGR 差", np.array(d_cagr) * 100, "%"), ("MDD 差", np.array(d_mdd) * 100, "%")):
    arr = np.array(arr)
    print(f"{nm}: 点估计 {np.mean(arr):+.2f}{unit}  5% {np.percentile(arr,5):+.2f}  "
          f"50% {np.percentile(arr,50):+.2f}  95% {np.percentile(arr,95):+.2f}  P(<0) {np.mean(arr<0)*100:.0f}%")

# ---- 交易特征
print("\n=== 仓位特征 ===")
for nm, W in (("V2", V2), ("V3", V3)):
    w = W["BTCUSDT"]
    on = (w > 0.02).astype(int)
    entries = int(((on.diff() == 1)).sum())
    expo = w.abs()
    print(f"{nm}: 平均仓位 {expo.mean()*100:.1f}%  满仓天数占比 {(w>0.5).mean()*100:.0f}%  "
          f"建仓次数 {entries}  平均持有 {len(w)/max(entries,1):.0f} 天  年换手 {W.diff().abs().sum(axis=1).mean()*365:.1f}")
