"""Conjunctions: is "everything lines up" a real state, or just fewer samples?

Single-axis tests were flat. The last honest attempt at a conviction signal is an AND of
the plausible ones -- strong z, moderate vol, shallow drawdown, clean trend. Conjunctions
shrink n fast, so each is judged on n, the directional edge, and then backtested as an
actual leverage rule against a flat control at matched average A.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep, show
from lev_d import running_dd
from lev_f import final_rules

pd.set_option("display.width", 260)


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
    Wd = W["BTCUSDT"].shift(1).fillna(0.0)
    act = Wd.abs() > 1e-9
    hit = np.sign(Wd) * r["BTCUSDT"]

    conds = {
        "全部有仓日（基线）": act,
        "|z|>1": act & (za > 1.0),
        "|z|>1 且 vol<45%": act & (za > 1.0) & (vv < 0.45),
        "|z|>1 且 dd>-10%": act & (za > 1.0) & (dd > -0.10),
        "|z|>1 且 ER>0.30": act & (za > 1.0) & (er > 0.30),
        "|z|>1 且 vol<45% 且 dd>-10%": act & (za > 1.0) & (vv < 0.45) & (dd > -0.10),
        "|z|>1 且 vol<40% 且 ER>0.35": act & (za > 1.0) & (vv < 0.40) & (er > 0.35),
        "|z|>1.5 且 vol<45% 且 dd>-10%": act & (za > 1.5) & (vv < 0.45) & (dd > -0.10),
    }

    print("=" * 116)
    print("A. 合取条件的方向收益。n 一旦掉到几百，Sharpe 的标准误就 >1，不可信")
    print("=" * 116)
    print(f"{'条件':<34}{'n':>6}{'占比':>7}{'均值bp':>9}{'胜率%':>7}{'Sharpe':>8}{'标准误':>8}{'去最好3天':>10}")
    for nm, m in conds.items():
        s = hit[m].dropna()
        se = np.sqrt(365 / len(s)) if len(s) else np.nan
        print(f"{nm:<34}{len(s):>6}{m.mean()*100:>6.0f}%{s.mean()*1e4:>9.1f}"
              f"{(s>0).mean()*100:>7.1f}{s.mean()/s.std()*np.sqrt(365):>8.2f}"
              f"{se:>8.2f}{s.sort_values().iloc[:-3].mean()*1e4:>10.1f}")

    print("\n" + "=" * 116)
    print("B. 把合取当杠杆开关：命中时 3x，否则 1x —— 与匹配平均杠杆的固定版比")
    print("=" * 116)
    rows = []
    for nm, m in list(conds.items())[1:]:
        A = pd.Series(1.0, index=C.index)
        A = A.mask(m.reindex(C.index).fillna(False), 3.0)
        mt, *_ = lev.simulate(W, A, *args, **kw)
        flat, *_ = lev.simulate(W, float(A.mean()), *args, **kw)
        print(f"\n--- {nm}   （命中 {int(m.sum())} 天，A均 {A.mean():.2f}x）")
        print(f"    开关版 : CAGR {mt['cagr']*100:6.1f}%  MDD {mt['mdd']*100:6.1f}%  "
              f"Sharpe {mt['sharpe']:.2f}  Calmar {mt['calmar']:.2f}  强平{mt['liq']}")
        print(f"    固定{A.mean():.2f}x: CAGR {flat['cagr']*100:6.1f}%  MDD {flat['mdd']*100:6.1f}%  "
              f"Sharpe {flat['sharpe']:.2f}  Calmar {flat['calmar']:.2f}  强平{flat['liq']}")
        verd = ("开关胜" if mt["calmar"] > flat["calmar"] and mt["sharpe"] >= flat["sharpe"] - 0.02
                else "固定胜")
        print(f"    -> {verd}")

    print("\n" + "=" * 116)
    print("C. 同样的开关，但只在命中时 2x（更温和）")
    print("=" * 116)
    for nm, m in list(conds.items())[1:]:
        A = pd.Series(1.0, index=C.index)
        A = A.mask(m.reindex(C.index).fillna(False), 2.0)
        mt, *_ = lev.simulate(W, A, *args, **kw)
        flat, *_ = lev.simulate(W, float(A.mean()), *args, **kw)
        print(f"{nm:<34} 开关 {mt['cagr']*100:6.1f}%/{mt['mdd']*100:6.1f}%/S{mt['sharpe']:.2f}  "
              f"固定{A.mean():.2f}x {flat['cagr']*100:6.1f}%/{flat['mdd']*100:6.1f}%/S{flat['sharpe']:.2f}  "
              f"{'开关胜' if mt['calmar'] > flat['calmar'] else '固定胜'}")


if __name__ == "__main__":
    main()
