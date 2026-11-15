"""Portfolio integration, with the index handling made explicit.

The failure mode this avoids: x starts 2020-06-02 and the carry series starts
2020-01-01; adding them silently extends the index to 2496 rows, and every
annualisation divides by the wrong number of days. Everything below is
reindexed onto one index and the identity is asserted, not assumed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import c1
import c3
import c5
import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"
START = "2020-06-01"


def legs():
    W, A, C, O, H, L, F = c5.v4_legs()
    return W, A, C, O, H, L, F


def carry_sources():
    F, P = c1.load()
    F, P, dp = c3.clean(F, P)
    btc = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                      c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1,
                                       floor=-1, basis_cap=None))
    alt = c1.simulate(F, P, c3.targets(F, P, dp, lookback=60, k=8, clock="M", hys=0.05))
    return btc.rename("btc"), alt.rename("alt")


def main():
    W, A, C, O, H, L, F = legs()
    c = C[S]

    # exact BTC carry from klines (what x10 used), for the control
    f = pd.read_parquet("data/perp/fnd_BTCUSDT.parquet")
    f["dt"] = pd.to_datetime(f["dt"], utc=True)
    fund = f.set_index("dt")["last_funding_rate"].resample("1D").sum()
    k = pd.read_parquet("data/perp/k1h_BTCUSDT.parquet")
    k["dt"] = pd.to_datetime(k["dt"], utc=True)
    perp = k.set_index("dt")["close"].resample("1D").last().reindex(c.index).ffill(limit=2)
    dn = (fund.reindex(c.index).fillna(0.0) - (perp / c - 1.0).diff().fillna(0.0)).rename("dn")

    btc, alt = carry_sources()
    blend = (0.75 * btc + 0.25 * alt).rename("blend")

    idx = c.loc[START:].index
    carry = pd.DataFrame({"dn": dn, "btc": btc, "alt": alt, "blend": blend}).reindex(idx)
    carry = carry.fillna(0.0)
    assert carry.index.equals(idx) and len(carry) == len(idx)
    print("carry panel", carry.shape, idx.min().date(), "->", idx.max().date())
    print((carry.mean() * BPY * 100).round(2).to_string(), " <- %/yr on notional")
    print("corr:\n", carry.corr().round(3).to_string())

    Wd = W[S].abs()
    A_ = A.reindex(idx)

    def run(name: str, lev_mult: float, carry_col: str | None):
        m, eq, ret, liq = lev.simulate(W, A * lev_mult, C, O, H, L, funding=F,
                                       liq=True, start=START, spot_base=True)
        x = ret.reindex(idx).fillna(0.0)
        assert len(x) == len(idx)
        if carry_col:
            gross = (Wd * A * lev_mult).shift(1).reindex(idx).fillna(0.0)
            idle = (1.0 - gross).clip(lower=0.0)
            x = x + (idle / 1.5) * carry[carry_col]
            assert len(x) == len(idx)
        e = (1 + x).cumprod()
        yrs = len(x) / BPY
        dd = e / e.cummax() - 1
        y = x.groupby(x.index.year).apply(lambda s: (1 + s).prod() - 1)
        h = len(x) // 2
        log_g = np.log1p(x).mean() * BPY
        return dict(cfg=name, mult=lev_mult, cagr=(e.iloc[-1] ** (1 / yrs) - 1) * 100,
                    vol=x.std() * np.sqrt(BPY) * 100,
                    sharpe=x.mean() / x.std() * np.sqrt(BPY),
                    mdd=dd.min() * 100, calmar=(e.iloc[-1] ** (1 / yrs) - 1) / abs(dd.min()),
                    log_g=log_g * 100, term=e.iloc[-1],
                    h1=x.iloc[:h].mean() / x.iloc[:h].std() * np.sqrt(BPY),
                    h2=x.iloc[h:].mean() / x.iloc[h:].std() * np.sqrt(BPY),
                    y22=y.get(2022, np.nan) * 100, y26=y.get(2026, np.nan) * 100), x

    rows, ser = [], {}
    rows.append(run("no carry", 1.0, None)[0])
    for col in ("dn", "btc", "alt", "blend"):
        m, x = run(f"carry {col}", 1.0, col)
        rows.append(m)
        ser[col] = x
    print("\n=== V4 at 1.0x ===")
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    rows = []
    for lm in (1.0, 1.25, 1.5, 2.0):
        rows.append(run(f"no carry {lm}x", lm, None)[0])
        rows.append(run(f"blend {lm}x", lm, "blend")[0])
    print("\n=== leverage ladder ===")
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n=== per-year (%) ===")
    t = pd.DataFrame(ser)
    print((t.groupby(t.index.year).apply(lambda d: (1 + d).prod() - 1) * 100).round(1).to_string())

    # sanity: the carry contribution must show up in log growth, ~1:1
    base = [r for r in rows if r["cfg"] == "no carry 1.0x"][0]["log_g"]
    for col in ("dn", "blend", "alt"):
        lg = [r for r in rows if r["cfg"] == f"carry {col}"][0]["log_g"]
        print(f"  log-growth gain from {col:5s}: {lg - base:+.2f}pp  "
              f"(carry itself {carry[col].mean()*BPY*100:.2f}%/yr on notional, "
              f"deployed at {(1 - (Wd*A).shift(1).reindex(idx).fillna(0)).clip(lower=0).mean()/1.5:.2f}x)")
    return carry


if __name__ == "__main__":
    main()
