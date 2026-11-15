"""The only arbiter that matters: does a timing overlay beat the same average leverage?

Every timing rule tested so far looked good in a tercile table and then lost to a
constant once leverage was matched. A tilt is only worth anything if it beats the
constant at EQUAL average exposure -- otherwise it is just a fancy way of buying
more risk, and buying more risk is available for free.

tk30 (30-day mean taker buy/sell volume ratio) is the one conditioner that survived
the within-year test (+57pp spread, 4 of 6 years). So test it the hard way:

  * schedule A = 1.5x in the top tercile of trailing-percentile tk30, 0.5x in the
    bottom, 1.0x in the middle
  * control  = constant A with exactly the same sample mean
  * also the reverse schedule, to see whether the effect has a sign at all
  * split-half, per-year, and a paired block bootstrap on the Sharpe difference
  * then repeat on ETH without re-fitting anything
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lev import load_perp, signal_weight, zscore
from oi_3 import daily_positioning

pd.set_option("display.width", 220)


def stats(pnl: pd.Series) -> dict:
    pnl = pnl.dropna()
    eq = (1 + pnl).cumprod()
    yrs = len(pnl) / 365.0
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1.0
    mdd = (eq / eq.cummax() - 1).min()
    vol = pnl.std() * np.sqrt(365)
    shp = pnl.mean() / pnl.std() * np.sqrt(365) if pnl.std() else np.nan
    return dict(cagr=cagr * 100, vol=vol * 100, mdd=mdd * 100, sharpe=shp,
                calmar=cagr / abs(mdd) if mdd else np.nan)


def build(sym="BTCUSDT"):
    C, O, H, L, F = load_perp([sym])
    c = C[sym]
    r = c.pct_change()
    vol = r.rolling(60).std() * np.sqrt(365)
    z = zscore(C)[sym]
    W = signal_weight(z, vol, enter=0.20, target_vol=0.40)

    p = daily_positioning(sym).reindex(c.index)
    p["tk"] = p["tk"].where(p["tk"] > 0)
    tk30 = p["tk"].rolling(30).mean()
    tk_pct = tk30.rolling(365, min_periods=120).rank(pct=True)

    d = pd.DataFrame({"ret": r, "vol": vol, "z": z, "w": W,
                      "tk30": tk30, "tk_pct": tk_pct})
    d = d.loc[d.index >= "2021-09-01"]      # needs a year of OI history to rank
    return d


def schedule(sig: pd.Series, hi=1.5, mid=1.0, lo=0.5, q=1 / 3):
    a = pd.Series(mid, index=sig.index)
    a = a.mask(sig >= 1 - q, hi)
    a = a.mask(sig <= q, lo)
    return a.fillna(mid)


def run(d, a: pd.Series, name: str) -> dict:
    # notional = w * A ; pnl uses yesterday's notional
    pnl = (d["w"] * a).shift(1) * d["ret"]
    s = stats(pnl)
    s["A_mean"] = a.mean()
    s["A_min"], s["A_max"] = a.min(), a.max()
    s["name"] = name
    return s, pnl


def boot_dsharpe(pa: pd.Series, pb: pd.Series, block=20, n=400, seed=11) -> tuple:
    """Paired moving-block bootstrap of Sharpe(a) - Sharpe(b)."""
    t = pd.concat([pa, pb], axis=1).dropna()
    x, y = t.iloc[:, 0].to_numpy(), t.iloc[:, 1].to_numpy()
    N = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(N / block))
    out = []
    for _ in range(n):
        st = rng.integers(0, N - block, nb)
        idx = np.concatenate([np.arange(s, s + block) for s in st])[:N]
        xs, ys = x[idx], y[idx]
        if xs.std() == 0 or ys.std() == 0:
            continue
        out.append((xs.mean() / xs.std() - ys.mean() / ys.std()) * np.sqrt(365))
    out = np.array(out)
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)), float((out <= 0).mean())


def main():
    for sym in ["BTCUSDT", "ETHUSDT"]:
        try:
            d = build(sym)
        except Exception as e:
            print(f"{sym}: {type(e).__name__} {e}")
            continue
        print(f"\n########## {sym}  n={len(d)}  {d.index.min().date()} -> {d.index.max().date()}")

        base, pnl_base = run(d, pd.Series(1.0, index=d.index), "A=1 constant")

        for lbl, (hi, mid, lo, rev) in {
                "tilt 1.5/1.0/0.5": (1.5, 1.0, 0.5, False),
                "tilt 2.0/1.0/0.5": (2.0, 1.0, 0.5, False),
                "tilt 3.0/1.0/1.0": (3.0, 1.0, 1.0, False),
                "REVERSE 2.0/1.0/0.5": (2.0, 1.0, 0.5, True)}.items():
            sig = (1 - d["tk_pct"]) if rev else d["tk_pct"]
            a = schedule(sig, hi, mid, lo)
            s_t, pnl_t = run(d, a, f"tk30 {lbl}")
            const = pd.Series(a.mean(), index=d.index)
            s_c, pnl_c = run(d, const, "matched constant")

            print(f"\n--- {lbl}  (avg A = {a.mean():.2f}x) ---")
            tab = pd.DataFrame([s_t, s_c])[
                ["name", "A_mean", "cagr", "vol", "mdd", "sharpe", "calmar"]]
            print(tab.round(3).to_string(index=False))
            lo_ci, hi_ci, pneg = boot_dsharpe(pnl_t, pnl_c)
            print(f"    dSharpe(tilt - constant) = {s_t['sharpe']-s_c['sharpe']:+.3f}  "
                  f"90% CI [{lo_ci:+.3f}, {hi_ci:+.3f}]  P(d<=0) = {pneg:.3f}")

            # split half
            for nm, sl in [("1H", slice(0, len(d) // 2)), ("2H", slice(len(d) // 2, None))]:
                a1 = stats(pnl_t.iloc[sl]); a2 = stats(pnl_c.iloc[sl])
                print(f"    {nm}: tilt {a1['cagr']:+6.1f}% S{a1['sharpe']:.2f} | "
                      f"const {a2['cagr']:+6.1f}% S{a2['sharpe']:.2f} | "
                      f"dS {a1['sharpe']-a2['sharpe']:+.3f}")


if __name__ == "__main__":
    main()
