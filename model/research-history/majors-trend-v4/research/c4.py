"""Does the alt book add anything to BTC carry, or is it the same trade twice?

The only question that decides adoption: correlation, then the blend, then
whether either survives without 2021.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import c1
import c3

CAP = c1.CAP_MULT


def boot(a: pd.Series, b: pd.Series, n=3000, seed=11):
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    rng = np.random.default_rng(seed)
    wk = j.index.to_period("W")
    groups = [g.to_numpy() for _, g in j.groupby(wk)]
    obs = (j.a.mean() / j.a.std() - j.b.mean() / j.b.std()) * np.sqrt(365)
    ds = []
    for _ in range(n):
        s = np.vstack([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        if s[:, 0].std() and s[:, 1].std():
            ds.append((s[:, 0].mean() / s[:, 0].std() - s[:, 1].mean() / s[:, 1].std()) * np.sqrt(365))
    ds = np.array(ds)
    return obs, (np.percentile(ds, 5), np.percentile(ds, 95)), (ds <= 0).mean()


def main():
    F, P = c1.load()
    F, P, dp = c3.clean(F, P)
    btc = c1.simulate(F[["BTCUSDT"]], P[["BTCUSDT"]],
                      c1.build_targets(F[["BTCUSDT"]], P[["BTCUSDT"]], k=1, floor=-1, basis_cap=None))
    W = c3.targets(F, P, dp, lookback=60, k=8, clock="M", hys=0.05)
    alt = c1.simulate(F, P, W)

    j = pd.concat([btc.rename("btc"), alt.rename("alt")], axis=1).dropna()
    print("correlation of daily carry returns: %.3f" % j.corr().iloc[0, 1])
    print("correlation of monthly: %.3f" % j.resample("ME").sum().corr().iloc[0, 1])

    rows = []
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        r = (1 - w) * j.btc + w * j.alt
        rows.append(c1.stats(r, f"BTC {100-w*100:.0f}% / alt {w*100:.0f}%"))
    c1.show(rows, "blend (same capital, 1.5x)")

    # ---- does it survive without 2021? ----
    print("\n===== excluding 2021 (the year that carries everything) =====")
    rows = []
    for nm, s in [("BTC only", j.btc), ("alt book", j.alt)]:
        t = s[s.index.year != 2021]
        rows.append(c1.stats(t, f"{nm}, ex-2021"))
    c1.show(rows, "ex-2021")

    # ---- halves ----
    h = len(j) // 2
    print("\n===== halves =====")
    for nm in ("btc", "alt"):
        a, b = j[nm].iloc[:h], j[nm].iloc[h:]
        print(f"  {nm:4s} H1 S {a.mean()/a.std()*np.sqrt(365):5.2f}  H2 S {b.mean()/b.std()*np.sqrt(365):5.2f}  "
              f"ann {a.mean()*365*100/CAP:5.1f}% / {b.mean()*365*100/CAP:5.1f}%")

    obs, ci, p = boot(j.alt, j.btc)
    print(f"\ndSharpe(alt - BTC) = {obs:+.3f}  90% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]  P(<=0)={p:.3f}")

    # ---- rolling 2y sharpe, to see decay ----
    print("\n===== rolling 2y Sharpe (annualised %) =====")
    roll = pd.DataFrame({
        "BTC": j.btc.rolling(730).apply(lambda x: x.mean() / x.std() * np.sqrt(365), raw=True),
        "alt": j.alt.rolling(730).apply(lambda x: x.mean() / x.std() * np.sqrt(365), raw=True),
    }).dropna().resample("QE").last()
    print(roll.round(2).tail(10).to_string())

    # ---- what the alt book actually holds, over time ----
    Wd = W.reindex(F.index).ffill().fillna(0)
    print("\n===== book composition, year end =====")
    comp = Wd.resample("YE").last() * 8
    comp = comp.loc[:, comp.sum() > 0]
    for d, row in comp.iterrows():
        held = row[row > 0].index.tolist()
        print(f"  {d.date()}  {', '.join(x.replace('USDT','') for x in held)}")

    # ---- concentration: how much of the return is one coin? ----
    contrib = (Wd.shift(1).fillna(0) * F.fillna(0)).sum()
    print("\n===== funding contribution by coin (% of book total) =====")
    c = (contrib / contrib.sum() * 100).sort_values(ascending=False)
    print(c.head(10).round(1).to_string())
    return j


if __name__ == "__main__":
    main()
