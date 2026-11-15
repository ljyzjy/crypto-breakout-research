"""Is the cross-sectional diversification real, or a survivor-panel artifact?

Checks, in the order that can kill it:
  1. split-half Sharpe difference
  2. bootstrap of the difference (paired, daily)
  3. vol-matched CAGR (both books at 40%)
  4. BTC weight sweep -- if the optimum is a knife-edge, it is fitting
  5. cost and start-date sensitivity
  6. leave-one-coin-out on the alt book
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab
from x3 import bt, core, C, O, V, uni

pd.set_option("display.width", 220)
BPY = 365
rng = np.random.default_rng(7)


def stats(ret, label=""):
    eq = (1 + ret).cumprod()
    yrs = len(ret) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    return dict(label=label, cagr=(eq.iloc[-1] ** (1 / yrs) - 1) * 100,
                vol=ret.std() * np.sqrt(BPY) * 100,
                sharpe=ret.mean() / ret.std() * np.sqrt(BPY),
                mdd=mdd * 100, calmar=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(mdd))


def sharpe(x):
    return x.mean() / x.std() * np.sqrt(BPY)


_, btc_r, _ = bt(core[["BTCUSDT"]], C, O, label="BTC")
alts = [c for c in core.columns if c != "BTCUSDT"]
_, alt_r, _ = bt(core[alts] / len(alts), C, O, label="alts")
_, all_r, _ = bt(core / len(core.columns), C, O, label="all24")

print("=== 1. split-half ===")
h = len(btc_r) // 2
for nm, a, b in (("BTC", btc_r, None), ("alts", alt_r, None), ("all24", all_r, None)):
    pass
rows = []
for nm, x in (("BTC", btc_r), ("alts23", alt_r), ("all24", all_r)):
    for i, seg in enumerate((x.iloc[:h], x.iloc[h:])):
        s = stats(seg)
        s["label"] = f"{nm} {'H1' if i == 0 else 'H2'}"
        rows.append(s)
blend = 0.5 * btc_r + 0.5 * alt_r
for i, seg in enumerate((blend.iloc[:h], blend.iloc[h:])):
    s = stats(seg)
    s["label"] = f"blend {'H1' if i == 0 else 'H2'}"
    rows.append(s)
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== 2. bootstrap: Sharpe(blend) - Sharpe(BTC), paired daily ===")
d = pd.DataFrame({"b": btc_r, "x": blend}).dropna()
bv, xv = d["b"].to_numpy(), d["x"].to_numpy()
obs = sharpe(pd.Series(xv)) - sharpe(pd.Series(bv))
ds = []
n = len(bv)
for _ in range(4000):
    i = rng.integers(0, n, n)
    ds.append(sharpe(pd.Series(xv[i])) - sharpe(pd.Series(bv[i])))
ds = np.array(ds)
print(f"  observed dSharpe {obs:+.3f}  90% CI [{np.percentile(ds, 5):+.3f}, "
      f"{np.percentile(ds, 95):+.3f}]  P(d<=0) {(ds <= 0).mean():.3f}")

print("\n=== 3. vol-matched to 40% (leverage both to the same risk) ===")
rows = []
for nm, x in (("BTC", btc_r), ("blend 50/50", blend), ("alts23", alt_r), ("all24", all_r)):
    s = stats(x)
    k = 40.0 / s["vol"]
    s2 = stats(x * k)
    s2["label"] = f"{nm} @40%vol (x{k:.2f})"
    rows.append(s2)
print(pd.DataFrame(rows).round(2).to_string(index=False))

print("\n=== 4. BTC weight sweep (risk split) ===")
for w in (0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0):
    x = w * btc_r + (1 - w) * alt_r
    s = stats(x)
    print(f"  BTC {w:.2f}: CAGR {s['cagr']:6.1f}%  vol {s['vol']:5.1f}%  "
          f"Sharpe {s['sharpe']:5.2f}  MDD {s['mdd']:6.1f}%")

print("\n=== 5. cost / start sensitivity on the blend ===")
for cost in (0.0005, 0.0010, 0.0020, 0.0030):
    _, rb, _ = bt(core[["BTCUSDT"]], C, O, cost=cost)
    _, ra, _ = bt(core[alts] / len(alts), C, O, cost=cost)
    x = 0.5 * rb + 0.5 * ra
    print(f"  cost {cost * 1e4:.0f}bp: blend Sharpe {sharpe(x.dropna()):5.2f}  "
          f"BTC {sharpe(rb):5.2f}   alts {sharpe(ra):5.2f}")
for st in ("2020-06-01", "2021-06-01", "2022-06-01", "2023-06-01"):
    x = (0.5 * btc_r + 0.5 * alt_r).loc[st:]
    print(f"  start {st}: blend Sharpe {sharpe(x):5.2f}  BTC {sharpe(btc_r.loc[st:]):5.2f}")

print("\n=== 6. leave-one-coin-out on the alt book (top contributors) ===")
contrib = {}
for c in alts:
    _, rc, _ = bt(core[[c]], C, O)
    contrib[c] = sharpe(rc)
top = sorted(contrib, key=contrib.get, reverse=True)[:4]
print("  best single alts:", {k: round(v, 2) for k, v in sorted(contrib.items(), key=lambda kv: -kv[1])[:4]})
for drop in top:
    keep = [c for c in alts if c != drop]
    _, rr, _ = bt(core[keep] / len(keep), C, O)
    x = (0.5 * btc_r + 0.5 * rr).dropna()
    print(f"  drop {drop:9s}: blend Sharpe {sharpe(x):5.2f}  (alts alone {sharpe(rr):5.2f})")
