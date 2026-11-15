"""The number that matters for planning: what this thing earns now, not on average.

A seven-year CAGR hides a regime change. Every year gets its own row, then a
rolling two-year Sharpe, then an estimate built only from the last 24 months.
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
    W, A, C, O, H, L, Fd = c6.legs()
    F, P = c1.load()
    F, P, dp = c3.clean(F, P)
    carry = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                        c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1,
                                         floor=-1, basis_cap=None))
    idx = C[S].loc["2020-06-01":].index
    gross = (W[S].abs() * A).shift(1).reindex(idx).fillna(0.0)
    idle = (1.0 - gross).clip(lower=0.0)

    def series(lev_mult=1.0, with_carry=True):
        m, eq, ret, liq = lev.simulate(W, A * lev_mult, C, O, H, L, funding=Fd,
                                       liq=True, start="2020-06-01", spot_base=True)
        x = ret.reindex(idx).fillna(0.0)
        if with_carry:
            x = x + (idle / 1.5) * carry.reindex(idx).fillna(0.0)
        return x

    trend = series(1.0, False)
    full = series(1.0, True)

    print("===== per-year: trend only vs trend + carry =====")
    rows = []
    for y, g in trend.groupby(trend.index.year):
        h = full[full.index.year == y]
        rows.append(dict(year=y, days=len(g),
                         t_ret=((1 + g).prod() - 1) * 100, t_vol=g.std() * np.sqrt(BPY) * 100,
                         t_shp=g.mean() / g.std() * np.sqrt(BPY),
                         c_ret=((1 + h).prod() - 1) * 100, c_shp=h.mean() / h.std() * np.sqrt(BPY)))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n===== rolling 2y Sharpe =====")
    roll = pd.DataFrame({
        "trend": trend.rolling(730).apply(lambda x: x.mean() / x.std() * np.sqrt(BPY), raw=True),
        "trend+carry": full.rolling(730).apply(lambda x: x.mean() / x.std() * np.sqrt(BPY), raw=True),
    }).dropna().resample("QE").last()
    print(roll.round(2).tail(12).to_string())

    print("\n===== recent windows, annualised =====")
    for lo, hi, nm in (("2023-01-01", "2026-10-31", "last ~4y"),
                       ("2024-01-01", "2026-10-31", "last ~3y"),
                       ("2024-11-01", "2026-10-31", "last 24m"),
                       ("2025-11-01", "2026-10-31", "last 12m")):
        for nm2, s in (("trend", trend), ("+carry", full)):
            t = s.loc[lo:hi]
            e = (1 + t).cumprod()
            yrs = len(t) / BPY
            print(f"  {nm:9s} {nm2:7s} ret {(e.iloc[-1]**(1/yrs)-1)*100:6.1f}%  "
                  f"vol {t.std()*np.sqrt(BPY)*100:5.1f}%  S {t.mean()/t.std()*np.sqrt(BPY):4.2f}  "
                  f"n={len(t)}")

    print("\n===== if the next 24 months look like the last 24 =====")
    t24 = full.loc["2024-11-01":]
    e = (1 + t24).cumprod()
    print(f"  realised 24m: {(e.iloc[-1]**(BPY/len(t24))-1)*100:.1f}%/yr, "
          f"vol {t24.std()*np.sqrt(BPY)*100:.1f}%, Sharpe {t24.mean()/t24.std()*np.sqrt(BPY):.2f}")

    print("\n===== worst windows (the tail you are actually buying) =====")
    e = (1 + full).cumprod()
    dd = e / e.cummax() - 1
    print(f"  max drawdown {dd.min()*100:.1f}% trough {dd.idxmin().date()}")
    for n in (30, 90):
        r = full.rolling(n).apply(lambda x: (1 + x).prod() - 1, raw=True)
        print(f"  worst {n}d {r.min()*100:.1f}%  ending {r.idxmin().date()}")
    return trend, full


if __name__ == "__main__":
    main()
