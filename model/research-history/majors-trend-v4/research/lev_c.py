"""Is the funding-gated short real, or did it just fit 2022?

Checks: yearly split, two half-samples, threshold sweep, percentile gate, paired bootstrap.
Also records when the first liquidation happens at high leverage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show

pd.set_option("display.width", 230)
RNG = np.random.default_rng(7)


def boot_sharpe_diff(ra, rb, n=4000):
    """Paired bootstrap of Sharpe(b) - Sharpe(a) on daily returns."""
    ra, rb = np.asarray(ra), np.asarray(rb)
    k = len(ra)
    d = np.empty(n)
    for i in range(n):
        j = RNG.integers(0, k, k)
        sa = ra[j].mean() / ra[j].std()
        sb = rb[j].mean() / rb[j].std()
        d[i] = sb - sa
    return (float(np.mean(d)), float(np.percentile(d, 5)),
            float(np.percentile(d, 95)), float((d > 0).mean()))


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]

    Wl = lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40)
    Wall = lev.signal_weight(z[sym], vol[sym], enter=0.20, target_vol=0.40, allow_short=True)
    Ws = Wall - Wl

    gate = (f > f.quantile(0.25)).astype(float)
    Wgs = Wl + Ws.mul(gate, axis=0)

    print("=== A. 分年（2x，收益 %）")
    runs = {}
    for name, W in (("只做多", Wl), ("多空对称", Wall), ("多空+资金费门", Wgs)):
        m, eq, ret, log = lev.simulate(W, 2, *args, **kw)
        runs[name] = ret
    tab = pd.DataFrame({k: ((1 + v).groupby(v.index.year).prod() - 1) * 100
                        for k, v in runs.items()}).round(1)
    tab["BTC"] = ((1 + C["BTCUSDT"].pct_change().reindex(runs["只做多"].index))
                  .groupby(runs["只做多"].index.year).prod() - 1).mul(100).round(1)
    print(tab.to_string())

    print("\n=== B. 全样本与分半")
    rows = []
    for name, v in runs.items():
        for lab, sl in (("全样本", slice(None)),
                        ("前半 20-23", slice("2020-01-01", "2023-06-30")),
                        ("后半 23-26", slice("2023-07-01", "2026-12-31"))):
            s = v.loc[sl] if isinstance(sl, slice) else v
            rows.append(dict(策略=name, 区间=lab,
                             sharpe=round(s.mean() / s.std() * np.sqrt(365), 2),
                             cagr=round(((1 + s).prod() ** (365 / len(s)) - 1) * 100, 1)))
    print(pd.DataFrame(rows).pivot(index="策略", columns="区间", values=["sharpe", "cagr"]).to_string())

    print("\n=== C. 门槛扫描（2x）")
    rows = []
    for q in (0.0, 0.10, 0.25, 0.40, 0.55):
        g = (f > f.quantile(q)).astype(float)
        W = Wl + Ws.mul(g, axis=0)
        m, *_ = lev.simulate(W, 2, *args, **kw)
        m["cfg"] = f"资金费分位>{q:.0%}  做空天数{float(g.mean())*100:.0f}%"
        rows.append(m)
    for th in (0.0, 0.0001, 0.0002, 0.0004, 0.0006):
        g = (f > th).astype(float)
        W = Wl + Ws.mul(g, axis=0)
        m, *_ = lev.simulate(W, 2, *args, **kw)
        m["cfg"] = f"资金费>{th*1e4:.1f}bp  做空天数{float(g.mean())*100:.0f}%"
        rows.append(m)
    print(show(rows))

    print("\n=== D. 配对自助：多空+门 相对 只做多 的 Sharpe 差")
    mu, lo, hi, p = boot_sharpe_diff(runs["只做多"], runs["多空+资金费门"])
    print(f"  ΔSharpe 均值 {mu:+.3f}  90%区间 [{lo:+.3f}, {hi:+.3f}]  P(Δ>0)={p:.2f}")
    mu2, lo2, hi2, p2 = boot_sharpe_diff(runs["只做多"], runs["多空对称"])
    print(f"  对称做空: ΔSharpe {mu2:+.3f}  90%区间 [{lo2:+.3f}, {hi2:+.3f}]  P(Δ>0)={p2:.2f}")

    print("\n=== E. 高倍率下第一次强平发生在什么时候")
    for A in (5, 8, 10, 12, 20, 40):
        m, eq, ret, log = lev.simulate(Wl, A, *args, **kw)
        if log:
            e = log[0]
            print(f"  {A:>2}x  首次强平 {str(e['dt'])[:10]}  当日逆向 {e['move']*100:+.1f}%  "
                  f"权益 {e['eq_before']:.2f} -> {e['eq_after']:.4f}  "
                  f"共 {len(log)} 次  | 期末 {(1+m['total']):.4f}")
        else:
            print(f"  {A:>2}x  无强平  期末 {1+m['total']:.2f}  回撤 {m['mdd']*100:.0f}%")


if __name__ == "__main__":
    main()
