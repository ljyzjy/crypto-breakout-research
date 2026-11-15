"""Final verdict on the 2x switch: does the edge survive halves and a bootstrap?

Section C of lev_m showed every switch "winning" on Calmar while Sharpe fell -- the
signature of buying return with volatility. Two things can rescue it: the gain shows up
in both halves of the sample, and a paired block bootstrap puts the Sharpe difference
above zero. Otherwise it is noise wearing a result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_d import running_dd
from lev_f import final_rules

pd.set_option("display.width", 260)
RNG = np.random.default_rng(20261114)


def sharpe(x):
    s = np.std(x, ddof=1)
    return np.mean(x) / s * np.sqrt(365) if s > 0 else np.nan


def boot_pair(r1, r2, block=20, n=3000):
    """Paired block bootstrap of the Sharpe difference (tilt minus flat)."""
    a, b = r1.to_numpy(), r2.to_numpy()
    T = len(a)
    nb = int(np.ceil(T / block))
    out = np.empty(n)
    for i in range(n):
        s = RNG.integers(0, T - block, size=nb)
        sel = (s[:, None] + np.arange(block)[None, :]).ravel()[:T]
        out[i] = sharpe(a[sel]) - sharpe(b[sel])
    return out


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]
    W, *_ = final_rules(C[sym], vol[sym], z[sym], f)
    _, _, r1x, _ = lev.simulate(W, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)
    za = z["BTCUSDT"].abs().shift(1)
    vv = vol["BTCUSDT"].shift(1)
    er = pd.read_parquet("out/conv_frame.parquet")["er"]
    act = W["BTCUSDT"].shift(1).abs() > 1e-9

    cands = {
        "|z|>1": act & (za > 1.0),
        "|z|>1 且 vol<45%": act & (za > 1.0) & (vv < 0.45),
        "|z|>1 且 vol<45% 且 dd>-10%": act & (za > 1.0) & (vv < 0.45) & (dd > -0.10),
        "|z|>1 且 vol<40% 且 ER>0.35": act & (za > 1.0) & (vv < 0.40) & (er > 0.35),
    }

    print("=" * 120)
    print("A. 分半：开关版与固定版在前后两段的表现（2x 开关）")
    print("=" * 120)
    for nm, m in cands.items():
        A = pd.Series(1.0, index=C.index).mask(m.reindex(C.index).fillna(False), 2.0)
        am = float(A.mean())
        _, _, rs, _ = lev.simulate(W, A, *args, **kw)
        _, _, rf, _ = lev.simulate(W, am, *args, **kw)
        print(f"\n--- {nm}   A均 {am:.2f}x   命中 {int(m.sum())} 天")
        for lbl, sl in (("2020-01~2023-03", slice("2020-01-01", "2023-03-31")),
                        ("2023-04~2026-10", slice("2023-04-01", None))):
            a, b = rs.loc[sl], rf.loc[sl]
            ca = ((1 + a).prod()) ** (365 / len(a)) - 1
            cb = ((1 + b).prod()) ** (365 / len(b)) - 1
            print(f"    {lbl}: 开关 C{ca*100:6.1f}% S{sharpe(a.to_numpy()):.2f} "
                  f"| 固定 C{cb*100:6.1f}% S{sharpe(b.to_numpy()):.2f} "
                  f"| ΔSharpe {sharpe(a.to_numpy())-sharpe(b.to_numpy()):+.2f}")

    print("\n" + "=" * 120)
    print("B. 配对分块自助：ΔSharpe（开关 - 固定）的分布")
    print("=" * 120)
    for nm, m in cands.items():
        A = pd.Series(1.0, index=C.index).mask(m.reindex(C.index).fillna(False), 2.0)
        am = float(A.mean())
        _, _, rs, _ = lev.simulate(W, A, *args, **kw)
        _, _, rf, _ = lev.simulate(W, am, *args, **kw)
        d = boot_pair(rs, rf)
        p = (d <= 0).mean()
        print(f"  {nm:<32} Δ均 {d.mean():+.3f}  [p5 {np.percentile(d,5):+.2f}, "
              f"p95 {np.percentile(d,95):+.2f}]  P(Δ<=0) {p:.2%}  "
              f"{'显著为正' if p < 0.05 else '不显著'}")

    print("\n" + "=" * 120)
    print("C. 逐年超额（开关 - 固定，百分点）")
    print("=" * 120)
    tab = {}
    for nm, m in cands.items():
        A = pd.Series(1.0, index=C.index).mask(m.reindex(C.index).fillna(False), 2.0)
        am = float(A.mean())
        _, _, rs, _ = lev.simulate(W, A, *args, **kw)
        _, _, rf, _ = lev.simulate(W, am, *args, **kw)
        ys = ((1 + rs).groupby(rs.index.year).prod() - 1) * 100
        yf = ((1 + rf).groupby(rf.index.year).prod() - 1) * 100
        tab[nm.split(" 且 ")[0] if "ER" not in nm else "z&vol&ER"] = (ys - yf)
    print(pd.DataFrame(tab).round(1).to_string())
    print("\n  若某方案在 5 年以上为正，才算稳定；忽正忽负就是噪声。")

    print("\n" + "=" * 120)
    print("D. 同样的开关能否提升「最终财富」而不只是 Calmar（复利口径）")
    print("=" * 120)
    for nm, m in cands.items():
        A = pd.Series(1.0, index=C.index).mask(m.reindex(C.index).fillna(False), 2.0)
        am = float(A.mean())
        es = lev.simulate(W, A, *args, **kw)[1]
        ef = lev.simulate(W, am, *args, **kw)[1]
        print(f"  {nm:<32} 期末倍数 开关 {es.iloc[-1]:7.1f}x | 固定 {ef.iloc[-1]:7.1f}x "
              f"| 差 {(es.iloc[-1]/ef.iloc[-1]-1)*100:+6.1f}%")


if __name__ == "__main__":
    main()
