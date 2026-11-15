"""Two questions, in order.

1. Out of sample: the alt book's parameters were picked on the full sample, which
   is exactly how a curve gets fitted. Pick them on the first half, run the second.
2. Integration: does any of this move the V4 portfolio, or is it a rounding error?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import c1
import c3
import lev

pd.set_option("display.width", 220)
BPY = 365
S = "BTCUSDT"


def v4_legs():
    C, O, H, L, F = lev.load_perp((S,))
    c = C[S]
    r = c.pct_change()
    vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
    z = lev.zscore(C)[S]
    px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
    tgt = (0.40 / vol).clip(upper=1.0)
    long_w = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    fnd = F[S]
    fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)
    short_w = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (long_w.fillna(0.0) - short_w.fillna(0.0)).to_frame(S)
    A = pd.Series(1.0, index=c.index)
    A = A.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
    A = A.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
    A = A.clip(1.0, 3.0)
    return W, A, C, O, H, L, F


def oos(F, P, dp):
    n = len(F)
    cut = int(n * 0.55)
    d1, d2 = F.index[cut], F.index[cut]
    print(f"split at {d1.date()}")

    grid = []
    for lb in (7, 30, 60, 120):
        for clock in ("W", "M"):
            for hys in (0.0, 0.02, 0.05):
                for k in (5, 8):
                    W = c3.targets(F, P, dp, lookback=lb, k=k, clock=clock, hys=hys)
                    r = c1.simulate(F, P, W)
                    a = r.loc[:d1]
                    grid.append(dict(lb=lb, clock=clock, hys=hys, k=k,
                                     h1=a.mean() / a.std() * np.sqrt(BPY)))
    g = pd.DataFrame(grid).sort_values("h1", ascending=False)
    print("\n===== top 5 on H1 only =====")
    print(g.head(5).round(2).to_string(index=False))

    btc = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                      c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1, floor=-1, basis_cap=None))
    print("\n===== H2 (never used for selection) =====")
    rows = [c1.stats(btc.loc[d2:], "BTC only, H2")]
    for _, row in g.head(3).iterrows():
        W = c3.targets(F, P, dp, lookback=int(row.lb), k=int(row.k),
                       clock=row.clock, hys=row.hys)
        r = c1.simulate(F, P, W)
        rows.append(c1.stats(r.loc[d2:], f"lb{int(row.lb)} {row.clock} hys{row.hys} k{int(row.k)}, H2"))
    # and the design that looked best in-sample, for contrast
    W = c3.targets(F, P, dp, lookback=60, k=8, clock="M", hys=0.05)
    rows.append(c1.stats(c1.simulate(F, P, W).loc[d2:], "in-sample pick, H2"))
    c1.show(rows, "out of sample")


def integrate():
    F, P = c1.load()
    F, P, dp = c3.clean(F, P)
    btc_carry = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                            c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1,
                                             floor=-1, basis_cap=None))
    alt_carry = c1.simulate(F, P, c3.targets(F, P, dp, lookback=60, k=8, clock="M", hys=0.05))
    blend = 0.75 * btc_carry + 0.25 * alt_carry

    W, A, C, O, H, L, Fp = v4_legs()
    c = C[S]
    f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
    f["dt"] = pd.to_datetime(f["dt"], utc=True)
    fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
    k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
    k["dt"] = pd.to_datetime(k["dt"], utc=True)
    perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
    dn = fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)

    print("\nBTC carry, two independent constructions (per unit notional, %/yr):")
    a1 = dn.loc["2020-06-01":]
    a2 = btc_carry.loc["2020-06-01":].reindex(a1.index).fillna(0)
    print(f"  perp/spot klines {a1.mean()*365*100:6.2f}   premium index {a2.mean()*365*100:6.2f}   "
          f"corr {a1.corr(a2):.3f}")

    def run(carry_series, label, lev_mult=1.0):
        m, eq, ret, liq = lev.simulate(W, A * lev_mult, C, O, H, L, funding=Fp,
                                       liq=True, start="2020-06-01", spot_base=True)
        x = ret.loc["2020-06-01":]
        if carry_series is not None:
            gross = (W[S].abs() * A * lev_mult).shift(1).fillna(0.0)
            idle = (1.0 - gross).clip(lower=0.0)
            x = x + ((idle / 1.5) * carry_series.reindex(x.index).fillna(0.0))
        eq2 = (1 + x).cumprod()
        yrs = len(x) / BPY
        dd = eq2 / eq2.cummax() - 1
        y = x.groupby(x.index.year).apply(lambda s: (1 + s).prod() - 1)
        h = len(x) // 2
        return dict(cfg=label, cagr=(eq2.iloc[-1] ** (1 / yrs) - 1) * 100,
                    vol=x.std() * np.sqrt(BPY) * 100,
                    sharpe=x.mean() / x.std() * np.sqrt(BPY),
                    mdd=dd.min() * 100,
                    calmar=(eq2.iloc[-1] ** (1 / yrs) - 1) / abs(dd.min()),
                    h1=x.iloc[:h].mean() / x.iloc[:h].std() * np.sqrt(BPY),
                    h2=x.iloc[h:].mean() / x.iloc[h:].std() * np.sqrt(BPY),
                    y22=y.get(2022, np.nan) * 100, y26=y.get(2026, np.nan) * 100), x

    rows, ser = [], {}
    for cs, lbl in ((None, "no carry"), (dn, "carry: BTC only"),
                    (btc_carry, "carry: BTC via premium"),
                    (blend, "carry: 75/25 blend"),
                    (alt_carry, "carry: alt book only")):
        m, x = run(cs, lbl)
        rows.append(m)
        ser[lbl] = x
    print("\n=== V4 with different carry sleeves (1.0x) ===")
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n=== then at 1.5x ===")
    rows = []
    for cs, lbl in ((None, "no carry"), (blend, "75/25 blend")):
        m, _ = run(cs, lbl, 1.5)
        rows.append(m)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    t = pd.DataFrame(ser)
    print("\n=== per-year (%) ===")
    print((t.groupby(t.index.year).apply(lambda d: (1 + d).prod() - 1) * 100).round(1).to_string())
    return ser


if __name__ == "__main__":
    F, P = c1.load()
    F, P, dp = c3.clean(F, P)
    oos(F, P, dp)
    integrate()
