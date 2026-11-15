"""Multi-coin funding carry: is a formal cross-sectional leg better than BTC-only?

Accounting, stated once so it cannot drift:
  A hedged book (long spot, short perp, equal notional) has P&L
      funding_received  -  change_in_basis
  because the two price legs cancel and only their ratio survives.
  Per unit of notional and for day t, with the position set at the close of t-1:
      r[t] = F[t] + (P[t-1] - P[t]) - cost[t]
  where F is the funding paid during day t and P is the premium index at the close.
  Nothing here is estimated: funding is a cash flow, the premium is a quote.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).resolve().parent / "data" / "carry"
CAP_MULT = 1.5          # spot (1.0) + perp margin (0.5) per unit of notional
SPOT_FEE, PERP_FEE = 0.0010, 0.0004


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    f = pd.read_parquet(D / "funding_long.parquet")
    p = pd.read_parquet(D / "premium_long.parquet")
    F = f.pivot_table(index="dt", columns="symbol", values="last_funding_rate", aggfunc="sum")
    P = p.pivot_table(index="dt", columns="symbol", values="prem", aggfunc="last")
    F = F.resample("1D").sum().replace(0.0, np.nan)
    P = P.resample("1D").last()
    idx = pd.date_range(min(F.index.min(), P.index.min()),
                        max(F.index.max(), P.index.max()), freq="D", tz="UTC")
    F, P = F.reindex(idx), P.reindex(idx)
    keep = [c for c in F.columns if F[c].notna().sum() > 250 and c in P.columns]
    return F[keep].sort_index(), P[keep].sort_index()


def stats(r: pd.Series, name: str, cap: float = CAP_MULT) -> dict:
    r = r.dropna()
    eq = (1 + r / cap).cumprod()
    dd = eq / eq.cummax() - 1
    yrs = len(r) / 365
    return dict(name=name, n=len(r),
                ann=(eq.iloc[-1] ** (1 / yrs) - 1) * 100,
                vol=r.std() * np.sqrt(365) / cap * 100,
                sharpe=r.mean() / r.std() * np.sqrt(365) if r.std() else np.nan,
                mdd=dd.min() * 100,
                worst=r.min() / cap * 100,
                calmar=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(dd.min()) if dd.min() else np.nan)


def show(rows: list[dict], title: str):
    d = pd.DataFrame(rows)
    cols = ["name", "n", "ann", "vol", "sharpe", "mdd", "worst", "calmar"]
    print(f"\n===== {title} =====")
    print(d[cols].round(2).to_string(index=False))


def build_targets(F: pd.DataFrame, P: pd.DataFrame, lookback: int = 7,
                  k: int = 5, floor: float = 0.03, reb: str = "W-MON",
                  basis_cap: float | None = 0.004) -> pd.DataFrame:
    """Target weights at each rebalance date, using data available that day.

    floor is annualised funding (0.03 = 3%/yr). basis_cap excludes coins whose
    premium is already stretched -- that is where the basis has the most room to
    snap back against a short-perp position.
    """
    sig = F.rolling(lookback, min_periods=max(2, lookback // 2)).mean() * 365
    ok = sig.notna() & F.notna()
    if basis_cap is not None:
        ok &= (P < basis_cap)

    # rebalance on the first trading day of each ISO week (Monday), or Thursday
    iso = F.index.isocalendar()
    dates = pd.Series(F.index, index=F.index).groupby([iso.year, iso.week]).first()
    if reb == "W-THU":
        dates = pd.Series(dates.values + pd.Timedelta(days=3), index=dates.index)

    # NB: list(dates) keeps tz-awareness; dates.values silently drops it to naive
    # numpy datetime64 and every lookup against the tz-aware index then misses.
    W = pd.DataFrame(0.0, index=pd.DatetimeIndex(list(dates)), columns=F.columns)
    for d in W.index:
        if d not in sig.index:
            continue
        s, good, px = sig.loc[d], ok.loc[d], P.loc[d]
        cand = s[good & (s > floor)].sort_values(ascending=False)
        # one slot per coin; equal notional; skip anything without a live premium
        cand = cand[px.reindex(cand.index).notna()]
        sel = cand.head(k).index
        if len(sel):
            W.loc[d, sel] = 1.0 / k          # gross <= 1; unfilled slots stay in cash
    return W


def simulate(F: pd.DataFrame, P: pd.DataFrame, Wt: pd.DataFrame,
             spot_fee: float = SPOT_FEE, perp_fee: float = PERP_FEE,
             cap: float = CAP_MULT, lag: int = 1) -> pd.Series:
    idx = F.index
    W = Wt.reindex(idx).ffill().fillna(0.0)
    W = W.shift(lag).fillna(0.0)             # decided at close of t-1, held over day t
    W = W * F.notna().astype(float)          # cannot hold what has no data

    fund = (W * F.fillna(0.0)).sum(axis=1)
    prem_prev = P.shift(1)
    basis = (W * (prem_prev - P).fillna(0.0)).sum(axis=1)
    trade = (W - W.shift(1).fillna(0.0)).abs().sum(axis=1)
    cost = trade * (spot_fee + perp_fee)
    return (fund + basis - cost).rename("ret")


def main():
    F, P = load()
    print("universe", len(F.columns), "days", len(F), F.index.min().date(), "->", F.index.max().date())
    print("coins:", ", ".join(F.columns))

    # ---------- per-coin, always-on (the raw material) ----------
    rows = []
    for c in F.columns:
        r = (F[c].fillna(0) + (P[c].shift(1) - P[c]).fillna(0))
        r = r[F[c].notna()]
        if len(r) < 250:
            continue
        st = stats(r, c)
        st["fund_ann"] = F[c].mean() * 365 * 100
        st["prem_med_bp"] = P[c].median() * 1e4
        rows.append(st)
    d = pd.DataFrame(rows).sort_values("fund_ann", ascending=False)
    print("\n===== per-coin always-on carry (1x notional, 1.5x capital) =====")
    print(d[["name", "n", "fund_ann", "prem_med_bp", "ann", "vol", "sharpe", "mdd", "worst"]]
          .round(2).to_string(index=False))

    # ---------- BTC-only benchmark (what we had) ----------
    base = simulate(F, P, build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1, floor=-1, basis_cap=None))
    show([stats(base, "BTC only")], "benchmark")

    # ---------- cross-sectional grid ----------
    rows = []
    for k in (1, 3, 5, 8, 12):
        for reb in ("W-MON",):
            Wt = build_targets(F, P, k=k, reb=reb)
            r = simulate(F, P, Wt)
            rows.append(stats(r, f"top{k} equal, {reb}"))
    show(rows, "K sweep (weekly, floor 3%/yr, basis<40bp)")

    rows = []
    Wt = build_targets(F, P, k=5)
    for floor in (-1.0, 0.0, 0.03, 0.06, 0.10):
        r = simulate(F, P, build_targets(F, P, k=5, floor=floor))
        rows.append(stats(r, f"floor {floor*100:.0f}%/yr"))
    show(rows, "funding floor sweep (top5 weekly)")

    rows = []
    for bc in (None, 0.010, 0.006, 0.004, 0.002):
        r = simulate(F, P, build_targets(F, P, k=5, basis_cap=bc))
        rows.append(stats(r, f"basis cap {bc}"))
    show(rows, "basis cap sweep (top5 weekly)")

    return F, P


if __name__ == "__main__":
    main()
