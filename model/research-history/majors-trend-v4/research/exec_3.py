"""If direction AUC is reliably below 0.50, there is mean reversion. Can it pay?

Ten independent segments all land between 0.476 and 0.494 -- a stable, if tiny, reversal
signal. The question is entirely arithmetic: does the spread between the top and bottom
decile of 1-hour returns exceed the 8bp round-trip taker cost, often enough to matter?
Tested both as a time-series quantile (each coin against itself) and cross-sectionally
(coins against each other at the same timestamp), because the two behave differently.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

pd.set_option("display.width", 240)
SRC = r"C:\Users\WIN11\Documents\Codex\2026-11-13\c-users-win11-documents-codex-2026-2\work\breakout_analysis\allbars.parquet"
COST_BP = 8.0          # taker 4bp x 2


def main():
    d = pd.read_parquet(SRC, columns=["ts", "symbol", "open", "close", "body",
                                      "ret1", "ret4", "volratio"])
    d = d.sort_values(["symbol", "ts"])
    d["fut"] = d.groupby("symbol")["body"].shift(-1)
    d = d.dropna(subset=["fut", "ret1", "ret4", "volratio"])
    d["dt"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
    print(f"样本 {len(d)} 根柱 / {d['symbol'].nunique()} 币   "
          f"{d['dt'].min().date()} -> {d['dt'].max().date()}")

    def bucket(s, k=10):
        return (s.rank(pct=True, method="first") * k).clip(upper=k - 0.001).astype(int)

    d["q_ts"] = d.groupby("symbol")["ret1"].transform(bucket)
    d["q_cs"] = d.groupby("ts")["ret1"].transform(bucket)
    d["q_vol"] = d.groupby("symbol")["volratio"].transform(bucket)

    for key, name in (("q_ts", "时序分位（每个币和它自己比）"),
                      ("q_cs", "横截面分位（同一时刻 18 币互比）")):
        print("\n" + "=" * 100)
        print(f"A. 按 ret1 的{name}分 10 组，看下一根柱实体（bp）")
        print("=" * 100)
        g = d.groupby(key)["fut"].agg(
            n="size",
            mean=lambda s: s.mean() * 1e4,
            med=lambda s: s.median() * 1e4,
            win=lambda s: (s > 0).mean() * 100,
            sd=lambda s: s.std() * 1e4)
        g["t"] = g["mean"] / (g["sd"] / np.sqrt(g["n"]))
        print(g.round(2).to_string())
        lo, hi = g["mean"].iloc[0], g["mean"].iloc[-1]
        gross = lo - hi
        print(f"\n  做多第0组 + 做空第9组：毛 {gross:+.2f}bp/根柱   "
              f"扣 {COST_BP:.0f}bp 往返 → 净 {gross - COST_BP:+.2f}bp")
        print(f"  → {'可行' if gross > COST_BP else '不可行，毛收益不够付手续费'}")

    print("\n" + "=" * 100)
    print("B. 只取极端信号（|ret1| 越大越极端），看毛收益随门槛怎么变")
    print("=" * 100)
    rows = []
    for q in (0.90, 0.95, 0.98, 0.99, 0.995):
        thr = d.groupby("symbol")["ret1"].transform(lambda s: s.abs().quantile(q))
        m = d["ret1"].abs() >= thr
        sub = d[m]
        if len(sub) < 100:
            continue
        # sign-aware: bet against the 1h move
        pnl = -np.sign(sub["ret1"]) * sub["fut"]
        rows.append(dict(门槛=f"|ret1|>p{q*100:.1f}", n=len(sub),
                         占比=len(sub) / len(d) * 100,
                         毛=pnl.mean() * 1e4,
                         净=pnl.mean() * 1e4 - COST_BP,
                         胜率=(pnl > 0).mean() * 100,
                         t=pnl.mean() / (pnl.std() / np.sqrt(len(pnl)))))
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    print("\n  「净」= 毛收益 − 8bp 往返成本。为正才值得做。")

    print("\n" + "=" * 100)
    print("C. 波动率分位 × 反转：低波时反转是否更可靠（成本占比更小）")
    print("=" * 100)
    rows = []
    for vq in (0, 2, 4, 6, 8):
        sub = d[d["q_vol"] == vq]
        if len(sub) < 1000:
            continue
        ts = sub["ts"].iloc[0]
        for key in ("q_ts",):
            lo = sub[sub[key] == 0]["fut"].mean() * 1e4
            hi = sub[sub[key] == 9]["fut"].mean() * 1e4
            med_abs = sub["fut"].abs().median() * 1e4
            rows.append(dict(波动组=vq, n=len(sub), 中位绝对实体=med_abs,
                             多空毛=lo - hi, 净=lo - hi - COST_BP,
                             成本占比=(COST_BP / (lo - hi) * 100) if lo - hi > 0 else np.nan))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n" + "=" * 100)
    print("D. 频率现实检查：一天 96 根柱，反转策略要交易多少次")
    print("=" * 100)
    thr = d.groupby("symbol")["ret1"].transform(lambda s: s.abs().quantile(0.95))
    m = (d["ret1"].abs() >= thr)
    per_day = m.groupby(d.loc[m, "dt"].dt.date).size()
    print(f"  |ret1|>p95 的柱：{int(m.sum())} 个，覆盖 {len(per_day)} 天")
    print(f"  平均每天 {per_day.mean():.1f} 个信号（若全做，年成本 "
          f"{per_day.mean()*365*COST_BP/1e4*100:.0f}% 的权益）")
    print(f"  注：这是单币口径。若一次只持 1 个仓位，实际交易次数远低于此。")


if __name__ == "__main__":
    main()
