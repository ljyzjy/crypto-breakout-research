"""Final tables for delivery: the leverage ladder, the condition table, and the equity path.

Recommended configuration is the three-tier ladder (1.75 / 1.25 / 1.0), which on 2020-2026
perp data gives a higher CAGR and a smaller drawdown than a constant 1.25x, at a slightly
lower Sharpe. Above 5x nothing is deliverable, and 8x or more ends the account.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import lev
from lev_a import prep
from lev_d import running_dd
from lev_f import final_rules
from lev_g import ladder

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
pd.set_option("display.width", 250)


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]

    W, Wl, Ws, gate = final_rules(C[sym], vol[sym], z[sym], f)
    _, _, r1x, _ = lev.simulate(W, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)
    A = ladder(vol["BTCUSDT"], dd, z["BTCUSDT"], tiers=(1.75, 1.25, 1.0))

    print("=== 1. 倍率全表（多空+资金费门，含强平与资金费）")
    rows, paths = [], {}
    for a in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 5.0, 8.0, 12.0, 20.0, 40.0):
        m, eq, ret, log = lev.simulate(W, a, *args, **kw)
        paths[a] = eq
        first = str(log[0]["dt"])[:10] if log else "-"
        rows.append(dict(倍率=f"{a:g}x", 年化=round(m["cagr"] * 100, 1),
                         波动=round(m["vol"] * 100, 0), Sharpe=round(m["sharpe"], 2),
                         最大回撤=round(m["mdd"] * 100, 1),
                         强平次数=m["liq"], 首次强平=first,
                         期末倍数=round(1 + m["total"], 3),
                         资金费成本=round(m["fund_pa"] * 100, 1)))
    m, eq, ret, log = lev.simulate(W, A, *args, **kw)
    paths["ladder"] = eq
    rows.append(dict(倍率="阶梯", 年化=round(m["cagr"] * 100, 1), 波动=round(m["vol"] * 100, 0),
                     Sharpe=round(m["sharpe"], 2), 最大回撤=round(m["mdd"] * 100, 1),
                     强平次数=m["liq"], 首次强平="-", 期末倍数=round(1 + m["total"], 3),
                     资金费成本=round(m["fund_pa"] * 100, 1)))
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== 2. 条件 → 倍率 → 实际表现")
    lat = pd.DataFrame({"A": A, "vol": vol["BTCUSDT"], "z": z["BTCUSDT"], "ret": ret}).dropna()
    lat["档位"] = lat["A"].round(2).map({1.0: "1.00x 默认", 1.25: "1.25x 正常", 1.75: "1.75x 顺势低波"})
    g = lat.groupby("档位", sort=False).agg(
        天数=("A", "size"),
        占比=("A", lambda s: f"{len(s)/len(lat)*100:.0f}%"),
        平均波动=("vol", lambda s: f"{s.mean()*100:.0f}%"),
        该档年化=("ret", lambda s: f"{((1+s).prod()**(365/len(s))-1)*100:+.0f}%"))
    print(g.to_string())

    print("\n=== 3. 分年（阶梯 vs 1x vs BTC）")
    yr = pd.DataFrame({
        "阶梯": ((1 + ret).groupby(ret.index.year).prod() - 1) * 100,
        "1x": ((1 + r1x).groupby(r1x.index.year).prod() - 1) * 100,
        "BTC": ((1 + C["BTCUSDT"].pct_change().reindex(ret.index))
                .groupby(ret.index.year).prod() - 1) * 100,
    })
    print(yr.round(1).to_string())

    print("\n=== 4. 各倍率的回撤容忍度映射")
    for a in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
        mm, _, rr, _ = lev.simulate(W, a, *args, **kw)
        print(f"  {a:>4.2f}x  回撤 {mm['mdd']*100:6.1f}%  年化 {mm['cagr']*100:6.1f}%  "
              f"最差单年 {lab_yearly(rr):.0f}%")

    # save
    for k, v in paths.items():
        tag = "ladder" if k == "ladder" else f"{k:g}x"
        v.to_frame("equity").to_csv(OUT / f"eq_{tag}.csv")
    lat.to_csv(OUT / "ladder_state.csv")
    (OUT / "final.json").write_text(json.dumps(dict(
        sample=f"{C.index[0].date()} -> {C.index[-1].date()}",
        ladder=dict(cagr=m["cagr"], mdd=m["mdd"], sharpe=m["sharpe"], liq=m["liq"]),
    ), indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n已保存 out/eq_*.csv, out/ladder_state.csv, out/final.json")


def lab_yearly(ret):
    y = (1 + ret).groupby(ret.index.year).prod() - 1
    return y.min() * 100


if __name__ == "__main__":
    main()
