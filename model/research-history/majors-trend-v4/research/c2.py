"""Is the cross-sectional carry leg real, or is it a survivorship artefact?

Four things have to be true before this is worth adding to V4:
  1. it beats BTC-only carry, not just "looks good on its own";
  2. the edge is not one year (2021) doing all the work;
  3. the basis, not the funding, is where the risk sits -- so measure the tails;
  4. costs and turnover are small relative to the income, at realistic fees.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import c1

CAP = c1.CAP_MULT


def yearly(r: pd.Series, cap: float = CAP) -> pd.DataFrame:
    g = r.groupby(r.index.year)
    out = pd.DataFrame({
        "ann%": g.mean() * 365 * 100 / cap,
        "vol%": g.std() * np.sqrt(365) * 100 / cap,
        "sharpe": g.mean() / g.std() * np.sqrt(365),
        "worst_day%": g.min() * 100 / cap,
        "days": g.size(),
    })
    return out.round(2)


def decomp(F, P, Wt, spot_fee=c1.SPOT_FEE, perp_fee=c1.PERP_FEE):
    idx = F.index
    W = Wt.reindex(idx).ffill().fillna(0.0).shift(1).fillna(0.0)
    W = W * F.notna().astype(float)
    fund = (W * F.fillna(0.0)).sum(axis=1)
    basis = (W * (P.shift(1) - P).fillna(0.0)).sum(axis=1)
    trade = (W - W.shift(1).fillna(0.0)).abs().sum(axis=1)
    cost = trade * (spot_fee + perp_fee)
    return fund, basis, cost, trade


def boot_delta(a: pd.Series, b: pd.Series, n: int = 4000, seed: int = 7):
    """Paired bootstrap on the Sharpe difference, block-resampled by week."""
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(j) < 200:
        return np.nan, (np.nan, np.nan), np.nan
    rng = np.random.default_rng(seed)
    wk = j.index.to_period("W")
    groups = [g.to_numpy() for _, g in j.groupby(wk)]
    obs = (j.a.mean() / j.a.std() - j.b.mean() / j.b.std()) * np.sqrt(365)
    ds = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        s = np.vstack([groups[i] for i in pick])
        if s[:, 0].std() == 0 or s[:, 1].std() == 0:
            continue
        ds.append((s[:, 0].mean() / s[:, 0].std() - s[:, 1].mean() / s[:, 1].std()) * np.sqrt(365))
    ds = np.array(ds)
    return obs, (np.percentile(ds, 5), np.percentile(ds, 95)), (ds <= 0).mean()


def main():
    F, P = c1.load()
    print("universe", len(F.columns), F.index.min().date(), "->", F.index.max().date())

    btc = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                      c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1, floor=-1, basis_cap=None))
    xs = c1.simulate(F, P, c1.build_targets(F, P, k=5))

    # ---------- 1. heads-up comparison ----------
    rows = [c1.stats(btc, "BTC only, always on"),
            c1.stats(xs, "top5 equal, weekly")]
    c1.show(rows, "cross-sectional vs BTC-only")

    fund, basis, cost, trade = decomp(F, P, c1.build_targets(F, P, k=5))
    print("\nP&L decomposition (per unit notional, annualised):")
    print(f"  funding  {fund.mean()*365*100:7.2f}%/yr   vol {fund.std()*np.sqrt(365)*100:6.2f}%")
    print(f"  basis    {basis.mean()*365*100:7.2f}%/yr   vol {basis.std()*np.sqrt(365)*100:6.2f}%")
    print(f"  cost     {-cost.mean()*365*100:7.2f}%/yr   turnover {trade.mean()*52:5.2f}x/week")
    print(f"  net      {(fund+basis-cost).mean()*365*100:7.2f}%/yr")

    # ---------- 2. by year ----------
    print("\n===== by year: BTC-only vs top5 =====")
    t = pd.concat([yearly(btc).add_prefix("btc_"), yearly(xs).add_prefix("xs_")], axis=1)
    print(t.to_string())

    # ---------- 3. tails: what basis can do ----------
    Pc = P[["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]]
    dp = (P.shift(1) - P)          # one-day basis pnl per unit notional
    print("\n===== worst one-day basis moves (pnl bp, per unit notional) =====")
    for c in P.columns:
        s = dp[c].dropna()
        if len(s) < 300:
            continue
        print(f"  {c:9s} min {s.min()*1e4:8.1f}bp on {s.idxmin().date()}   "
              f"p1 {np.percentile(s,1)*1e4:6.1f}bp   p99 {np.percentile(s,99)*1e4:6.1f}bp")
    W = c1.build_targets(F, P, k=5).reindex(F.index).ffill().fillna(0).shift(1).fillna(0)
    W = W * F.notna().astype(float)
    per_coin_basis = (W * (P.shift(1) - P)).fillna(0)
    book = per_coin_basis.sum(axis=1)
    print(f"\nbook basis shock: worst day {book.min()*1e4:.1f}bp, "
          f"worst 5d {book.rolling(5).sum().min()*1e4:.1f}bp, "
          f"worst 20d {book.rolling(20).sum().min()*1e4:.1f}bp")
    print("top 5 losing days:")
    print((book.nsmallest(5) * 1e4).round(1).to_string())

    # ---------- 4. costs ----------
    print("\n===== cost sensitivity (funding is the income, fees are the drag) =====")
    rows = []
    for sf, pf in [(0.0004, 0.0002), (0.0010, 0.0004), (0.0020, 0.0008), (0.0040, 0.0016)]:
        r = c1.simulate(F, P, c1.build_targets(F, P, k=5), spot_fee=sf, perp_fee=pf)
        rows.append(c1.stats(r, f"spot {sf*1e4:.0f}bp / perp {pf*1e4:.0f}bp"))
    c1.show(rows, "fees")

    # ---------- 5. halve ----------
    h = len(xs) // 2
    print("\n===== halves =====")
    for nm, s in [("BTC only", btc), ("top5", xs)]:
        a, b = s.iloc[:h], s.iloc[h:]
        print(f"  {nm:9s} H1 {a.mean()/a.std()*np.sqrt(365):5.2f}  "
              f"H2 {b.mean()/b.std()*np.sqrt(365):5.2f}   "
              f"ann {a.mean()*365*100/CAP:5.1f}% / {b.mean()*365*100/CAP:5.1f}%")
    obs, ci, p = boot_delta(xs, btc)
    print(f"  dSharpe(top5 - BTC) = {obs:+.3f}  90% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]  P(<=0)={p:.3f}")

    # ---------- 6. who is in the book ----------
    Wr = c1.build_targets(F, P, k=5)
    cnt = (Wr > 0).sum()
    print("\n===== days selected (top5, weekly) =====")
    print(cnt.sort_values(ascending=False).to_string())

    return F, P, btc, xs


if __name__ == "__main__":
    main()
