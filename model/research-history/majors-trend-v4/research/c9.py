"""What the carry sleeve is actually worth going forward, and what limits it.

Two things decide this, and neither is coin selection:
  * the level of funding, which has fallen from 30%/yr in 2021 to ~3% in 2026;
  * the capital rule, 1.5 units of capital per unit of notional, because spot
    cannot collateralise a USDⓈ-M short on a classic account.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import c1
import c3
import c6
import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"


def main():
    F, P = c1.load()
    F, P, dp = c3.clean(F, P)

    print("===== funding by year, %/yr on notional =====")
    btc = (F["BTCUSDT"] * 365 * 100).groupby(F.index.year).mean().rename("BTC")
    alts = [c for c in F.columns if c != "BTCUSDT"]
    top = (F[alts].mean(axis=1) * 365 * 100).groupby(F.index.year).mean().rename("alt equal-weight")
    bks = pd.DataFrame({"BTC": btc, "alt eq-w": top})
    print(bks.round(2).to_string())

    print("\n===== what the sleeve contributes at each funding regime =====")
    W, A, C, O, H, L, Fd = c6.legs()
    carry_btc = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                            c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1,
                                             floor=-1, basis_cap=None))
    idx = C[S].loc["2020-06-01":].index
    gross = (W[S].abs() * A).shift(1).reindex(idx).fillna(0.0)
    idle = (1.0 - gross).clip(lower=0.0)
    deploy = idle / 1.5
    print(f"  average idle capital {idle.mean():.3f}  -> carry notional {deploy.mean():.3f}x capital")

    rows = []
    for lo, hi, nm in (("2020-01-01", "2021-12-31", "2020-2021"),
                       ("2022-01-01", "2023-12-31", "2022-2023"),
                       ("2024-01-01", "2025-12-31", "2024-2025"),
                       ("2026-01-01", "2026-10-31", "2026 YTD")):
        m = (idx >= lo) & (idx <= hi)
        y = (deploy[m] * carry_btc.reindex(idx).fillna(0)[m]).mean() * BPY * 100
        rows.append(dict(period=nm, fund_bps=float(F["BTCUSDT"].loc[lo:hi].mean() * 1e4),
                         carry_add_pp=y))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n===== capital multiplier: the binding constraint =====")
    rows = []
    for cap in (1.5, 1.35, 1.2, 1.05):
        x = None
        m, eq, ret, liq = lev.simulate(W, A, C, O, H, L, funding=Fd,
                                       liq=True, start="2020-06-01", spot_base=True)
        base = ret.reindex(idx).fillna(0.0)
        add = (idle / cap) * carry_btc.reindex(idx).fillna(0.0)
        y = base + add
        e = (1 + y).cumprod()
        yrs = len(y) / BPY
        dd = e / e.cummax() - 1
        h = len(y) // 2
        rows.append(dict(cap_mult=cap,
                         carry_notional=float((idle / cap).mean()),
                         cagr=(e.iloc[-1] ** (1 / yrs) - 1) * 100,
                         sharpe=y.mean() / y.std() * np.sqrt(BPY),
                         mdd=dd.min() * 100,
                         h1=y.iloc[:h].mean() / y.iloc[:h].std() * np.sqrt(BPY),
                         h2=y.iloc[h:].mean() / y.iloc[h:].std() * np.sqrt(BPY)))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n===== forward planning numbers (2026 funding only) =====")
    m26 = idx.year == 2026
    f26 = float(F["BTCUSDT"].loc["2026-01-01":].mean() * BPY)
    d26 = float(deploy[m26].mean())
    print(f"  2026 BTC funding {f26*100:.2f}%/yr on notional")
    print(f"  2026 average carry notional {d26:.3f}x capital")
    print(f"  -> carry adds {f26*d26*100:.2f}pp of CAGR at 1.5x capital")
    print(f"  -> at 1.2x capital it adds {f26*d26*1.5/1.2*100:.2f}pp")
    print(f"  -> at 1.05x capital it adds {f26*d26*1.5/1.05*100:.2f}pp")


if __name__ == "__main__":
    main()
