"""The alt book's problem was turnover, not basis. Fix turnover, then re-judge.

c2 measured: funding 16.8%/yr, basis +0.3%, cost -7.7% (55 turns/yr) -> 9.4% net.
So the edge exists in the funding and is spent on the rebalancing. Three levers:
  * a slower signal (30/60d instead of 7d) -- the ranking stops churning;
  * a slower clock (monthly instead of weekly);
  * hysteresis -- an incumbent keeps its slot unless a challenger is clearly better.

Also cleans two data faults that would otherwise be read as risk:
  * the first 30 days after a perp lists (FIL printed a -15% basis quote on day 3);
  * basis moves beyond 200bp/day are treated as broken quotes, not P&L.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import c1

CAP = c1.CAP_MULT
MIN_HIST = 30
BASIS_CLIP = 0.02


def clean(F: pd.DataFrame, P: pd.DataFrame):
    """Drop listing-period noise and cap single-day basis quotes at 200bp."""
    first = F.apply(lambda s: s.first_valid_index())
    age = pd.DataFrame({c: (F.index - first[c]).days for c in F.columns}, index=F.index)
    F = F.where(age >= MIN_HIST)
    dp = (P.shift(1) - P).clip(-BASIS_CLIP, BASIS_CLIP)
    return F, P, dp


def targets(F, P, dp, lookback=30, k=5, floor=0.03, clock="M", hys=0.02,
            basis_cap=0.004, rank="fund"):
    sig = F.rolling(lookback, min_periods=max(3, lookback // 3)).mean() * 365
    ok = sig.notna() & F.notna() & (P < basis_cap) if basis_cap is not None else sig.notna() & F.notna()

    if clock == "M":
        dates = pd.Series(F.index, index=F.index).groupby(
            [F.index.year, F.index.month]).first()
    elif clock == "W":
        iso = F.index.isocalendar()
        dates = pd.Series(F.index, index=F.index).groupby([iso.year, iso.week]).first()
    else:
        dates = pd.Series(F.index, index=F.index)

    if rank == "fund":
        score = sig
    else:  # funding per unit of basis risk: the carry analogue of a Sharpe rank
        bv = dp.rolling(60, min_periods=20).std() * 1e4
        score = sig / bv.clip(lower=1.0)

    W = pd.DataFrame(0.0, index=pd.DatetimeIndex(list(dates)), columns=F.columns)
    held: list[str] = []
    for d in W.index:
        if d not in score.index:
            continue
        s, good = score.loc[d], ok.loc[d]
        live = good & s.notna()
        if live.sum() == 0:
            held = []
            continue
        adj = s.copy()
        adj[held] = adj[held] + hys                 # incumbency premium, in sig units
        cand = adj[live & (s > floor - hys)].sort_values(ascending=False)
        sel = list(cand.head(k).index)
        if sel:
            W.loc[d, sel] = 1.0 / k
        held = sel
    return W


def run(F, P, dp, **kw):
    W = targets(F, P, dp, **kw)
    r = c1.simulate(F, P, W)
    fund = (W.reindex(F.index).ffill().fillna(0).shift(1).fillna(0)
            * F.notna() * F.fillna(0)).sum(axis=1)
    tr = (W.reindex(F.index).ffill().fillna(0).shift(1).fillna(0)
          - W.reindex(F.index).ffill().fillna(0).shift(2).fillna(0)).abs().sum(axis=1)
    return r, tr.mean() * 365


def main():
    F0, P0 = c1.load()
    F, P, dp = clean(F0, P0)
    btc = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                      c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1, floor=-1, basis_cap=None))
    print("===== benchmark =====")
    c1.show([c1.stats(btc, "BTC only")], "BTC only")

    rows = []
    for lb in (7, 30, 60, 120):
        for clock in ("W", "M"):
            for hys in (0.0, 0.02, 0.05):
                r, to = run(F, P, dp, lookback=lb, k=5, clock=clock, hys=hys)
                st = c1.stats(r, f"lb{lb} {clock} hys{hys*100:.0f}pp")
                st["turn/yr"] = to
                rows.append(st)
    c1.show(rows, "turnover levers (top5)")

    print("\n===== best-of-grid detail =====")
    best, bt = None, None
    for lb in (30, 60):
        for clock in ("M",):
            for hys in (0.02, 0.05):
                r, to = run(F, P, dp, lookback=lb, k=5, clock=clock, hys=hys)
                st = c1.stats(r, f"lb{lb} {clock} hys{hys}")
                if best is None or st["sharpe"] > best["sharpe"]:
                    best, bt = st, r
    print(pd.DataFrame([best]).round(2).to_string(index=False))

    rows = []
    for k in (3, 5, 8, 12, 25):
        r, to = run(F, P, dp, lookback=60, k=k, clock="M", hys=0.05)
        st = c1.stats(r, f"top{k}")
        st["turn/yr"] = to
        rows.append(st)
    c1.show(rows, "basket width (lb60 monthly hys5)")

    rows = []
    for capv in (None, 0.006, 0.004, 0.002):
        r, to = run(F, P, dp, lookback=60, k=8, clock="M", hys=0.05, basis_cap=capv)
        st = c1.stats(r, f"basis<{capv}")
        st["turn/yr"] = to
        rows.append(st)
    c1.show(rows, "basis filter")

    rows = []
    for rk in ("fund", "risk"):
        r, to = run(F, P, dp, lookback=60, k=8, clock="M", hys=0.05, rank=rk)
        st = c1.stats(r, f"rank={rk}")
        st["turn/yr"] = to
        rows.append(st)
    c1.show(rows, "ranking rule")

    # attribution once more, on the chosen design
    W = targets(F, P, dp, lookback=60, k=8, clock="M", hys=0.05)
    Wd = W.reindex(F.index).ffill().fillna(0).shift(1).fillna(0) * F.notna()
    fund = (Wd * F.fillna(0)).sum(axis=1)
    basis = (Wd * dp).sum(axis=1)
    tr = (Wd - Wd.shift(1).fillna(0)).abs().sum(axis=1)
    cost = tr * (c1.SPOT_FEE + c1.PERP_FEE)
    print("\n===== chosen design: top8, lb60, monthly, hys5pp, basis<40bp =====")
    print(f"  funding {fund.mean()*365*100:6.2f}%/yr   basis {basis.mean()*365*100:6.2f}%/yr   "
          f"cost {-cost.mean()*365*100:5.2f}%/yr   turns {tr.mean()*365:5.1f}/yr")
    print(f"  net     {(fund+basis-cost).mean()*365*100:6.2f}%/yr on notional")
    c1.show([c1.stats(c1.simulate(F, P, W), "top8 lb60 M")], "chosen")

    r = c1.simulate(F, P, W)
    print("\nby year:")
    g = r.groupby(r.index.year)
    print(pd.DataFrame({"ann%": g.mean() * 365 * 100 / CAP, "vol%": g.std() * np.sqrt(365) * 100 / CAP,
                        "sharpe": g.mean() / g.std() * np.sqrt(365),
                        "worst%": g.min() * 100 / CAP}).round(2).to_string())
    return F, P, dp, btc, r


if __name__ == "__main__":
    main()
