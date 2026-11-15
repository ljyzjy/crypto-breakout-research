"""Final parameter set, bucket table, and a 2017-2026 stress test outside the perp sample.

The perp archive starts 2020-01, which means the 2018 bear market is not in it. The
schedule must still be checked there, using the spot panel with funding charged at the
historical average (long-only, no shorts since there was no perp to short in 2018).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import lev
import lab
import opt
from lev_a import prep, show
from lev_d import schedule, running_dd

pd.set_option("display.width", 250)


def final_rules(C, vol, z, f, win=365, q=0.40):
    """Long always allowed; short only when funding sits in the upper part of its
    trailing one-year distribution. The quantile is rolling, not full-sample, so the
    gate never sees the future."""
    Wl = lev.signal_weight(z, vol, enter=0.20, target_vol=0.40)
    Ws = lev.signal_weight(z, vol, enter=0.20, target_vol=0.40, allow_short=True) - Wl
    thr = f.rolling(win, min_periods=120).quantile(q)
    gate = (f > thr).astype(float).fillna(1.0)
    return Wl + Ws.mul(gate, axis=0), Wl, Ws, gate


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]

    W, Wl, Ws, gate = final_rules(C[sym], vol[sym], z[sym], f)
    _, _, r1x, _ = lev.simulate(W, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)

    print("=== A. 波动分布：什么条件下才谈得上高倍率")
    v = vol["BTCUSDT"].dropna()
    print(f"  60日年化波动: 最低 {v.min()*100:.0f}%  中位 {v.median()*100:.0f}%  "
          f"p10 {v.quantile(.1)*100:.0f}%  最高 {v.max()*100:.0f}%")
    print("  若要条件倍率打到 40x，需要波动降到 %.1f%% —— 历史最低是 %.0f%%" %
          (100 / 40, v.min() * 100))

    print("\n=== B. 条件 → 倍率 → 该状态下的实际表现（预算 50%，2x 上限参考）")
    A = schedule(vol["BTCUSDT"], dd, risk_budget=0.50, cap=5.0)
    _, _, retA, _ = lev.simulate(W, A, *args, **kw)
    bk = pd.cut(vol["BTCUSDT"], [0, .30, .45, .60, .80, 9.9],
                labels=["σ<30%", "30-45%", "45-60%", "60-80%", "σ>80%"])
    t = pd.DataFrame({"A": A, "bucket": bk, "ret": retA, "vol": vol["BTCUSDT"]}).dropna()
    g = t.groupby("bucket", observed=True).agg(
        天数=("A", "size"), 倍率均值=("A", "mean"), 倍率区间=("A", lambda s: f"{s.min():.1f}-{s.max():.1f}"),
        该状态年化=("ret", lambda s: ((1 + s).prod() ** (365 / len(s)) - 1) * 100))
    g["占比%"] = (g["天数"] / len(t) * 100).round(0)
    g["倍率均值"] = g["倍率均值"].round(2)
    g["该状态年化"] = g["该状态年化"].round(1)
    print(g[["占比%", "倍率均值", "倍率区间", "该状态年化"]].to_string())

    print("\n=== C. 预算分档的完整指标（多空+空头门，条件倍率）")
    rows = []
    for rb in (0.35, 0.50, 0.65, 0.80, 1.00):
        A_ = schedule(vol["BTCUSDT"], dd, risk_budget=rb, cap=5.0)
        m, eq, ret, log = lev.simulate(W, A_, *args, **kw)
        m["cfg"] = f"预算{int(rb*100)}%"
        m["A中位"] = float(A_.median())
        m["A最大"] = float(A_.max())
        rows.append(m)
    d = pd.DataFrame(rows)
    for c in ("cagr", "vol", "mdd", "fund_pa", "expo"):
        d[c] = (d[c] * 100).round(1)
    print(d[["cfg", "A中位", "A最大", "cagr", "vol", "sharpe", "mdd", "calmar", "liq", "fund_pa", "expo"]]
          .round(2).to_string(index=False))

    print("\n=== D. 分年（预算 50% 与 80%）")
    yrs = {}
    for rb in (0.50, 0.80, 1.00):
        A_ = schedule(vol["BTCUSDT"], dd, risk_budget=rb, cap=5.0)
        _, _, rr, _ = lev.simulate(W, A_, *args, **kw)
        yrs[f"预算{int(rb*100)}%"] = ((1 + rr).groupby(rr.index.year).prod() - 1) * 100
    bench = C["BTCUSDT"].pct_change()
    yrs["BTC"] = ((1 + bench.reindex(rr.index)).groupby(rr.index.year).prod() - 1) * 100
    yrs["BTC回撤"] = ""
    print(pd.DataFrame(yrs).round(1).to_string())

    # ---------------------------------------------------------------- 2017-2026 stress
    print("\n=== E. 出样本压测：2017-08 → 2026-10（现货面板，资金费按均值扣）")
    Ce, Oe, He, Le = opt.load_long(("BTCUSDT",))
    Ce = Ce[["BTCUSDT"]].loc["2017-08-17":].ffill(limit=3)
    Oe = Oe[["BTCUSDT"]].reindex(Ce.index).ffill(limit=3)
    He = He[["BTCUSDT"]].reindex(Ce.index).ffill(limit=3)
    Le = Le[["BTCUSDT"]].reindex(Ce.index).ffill(limit=3)
    ve = (Ce.pct_change().rolling(60).std() * np.sqrt(365)).clip(lower=0.05)
    ze = lev.zscore(Ce, (20, 40, 60, 90))
    We = lev.signal_weight(ze, ve, enter=0.20, target_vol=0.40)
    Fq = pd.DataFrame({"BTCUSDT": 3.19e-4}, index=Ce.index)   # 2020-2026 perp 均值

    rows = []
    for lab_, A_ in (("1x", 1.0), ("2x", 2.0), ("条件 35%", schedule(ve["BTCUSDT"], pd.Series(0.0, index=Ce.index), 0.35, 5.0)),
                     ("条件 50%", schedule(ve["BTCUSDT"], pd.Series(0.0, index=Ce.index), 0.50, 5.0)),
                     ("条件 80%", schedule(ve["BTCUSDT"], pd.Series(0.0, index=Ce.index), 0.80, 5.0))):
        m, eq, ret, log = lev.simulate(We, A_, Ce, Oe, He, Le, Fq,
                                      start="2018-01-01", reenter=True)
        m["cfg"] = lab_
        rows.append(m)
    d2 = pd.DataFrame(rows)
    for c in ("cagr", "vol", "mdd", "fund_pa", "expo"):
        d2[c] = (d2[c] * 100).round(1)
    print(d2[["cfg", "cagr", "vol", "sharpe", "mdd", "calmar", "liq", "fund_pa", "expo"]]
          .round(2).to_string(index=False))

    print("\n  2018 单年（BTC -72%）:")
    for lab_, A_ in (("1x", 1.0), ("2x", 2.0),
                     ("条件 50%", schedule(ve["BTCUSDT"], pd.Series(0.0, index=Ce.index), 0.50, 5.0))):
        _, _, ret, _ = lev.simulate(We, A_, Ce, Oe, He, Le, Fq, start="2018-01-01")
        y = ((1 + ret).groupby(ret.index.year).prod() - 1) * 100
        print(f"    {lab_:>8}: " + "  ".join(f"{k} {v:+.0f}%" for k, v in y.items()))

    # save outputs for the write-up
    A50 = schedule(vol["BTCUSDT"], dd, risk_budget=0.50, cap=5.0)
    m, eq, ret, log = lev.simulate(W, A50, *args, **kw)
    out = dict(
        sample=f"{C.index[0].date()} -> {C.index[-1].date()}",
        metrics={k: (float(v) if not isinstance(v, list) else v) for k, v in m.items()},
        vol_min=float(v.min()), vol_med=float(v.median()),
    )
    pd.Series(eq.values, index=eq.index).to_frame("equity").to_csv("out/v4_equity.csv")
    (lev.D / ".." / "out" / "v4_summary.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n已保存 out/v4_equity.csv 与 out/v4_summary.json")


if __name__ == "__main__":
    main()
