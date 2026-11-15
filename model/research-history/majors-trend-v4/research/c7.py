"""Does funding predict the next week's return, cross-sectionally?

This is the one directional question my data can still answer that I have never
asked. Funding is the price of leverage: when it is extreme, positioning is
crowded. If that crowding mean-reverts, high-funding coins underperform -- and
that is a tradable short with a funding credit attached, not just a filter.

Rules kept from earlier rounds so the result is comparable:
  * weekly, non-overlapping;
  * signal at the close of day t, fill at the open of t+1, exit at the open of t+8;
  * rank IC, by year and by half, before any backtest.
Kill line from the 15-minute study: |IC| below 0.02 with t under 2 is noise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import c1

BAD = {"LUNAUSDT", "FTTUSDT"}      # spliced series / 311 missing days


def panels():
    F, P = c1.load()
    d = pd.read_parquet("data/daily/daily_panel.parquet")
    d["dt"] = pd.to_datetime(d["dt"], utc=True)
    O = d.pivot_table(index="dt", columns="symbol", values="open", aggfunc="last")
    C = d.pivot_table(index="dt", columns="symbol", values="close", aggfunc="last")
    cols = [c for c in F.columns if c in O.columns and c not in BAD]
    return F[cols], P[cols], O[cols], C[cols]


def weekly_grid(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Fridays (last trading day of each ISO week) -- the decision points."""
    iso = idx.isocalendar()
    s = pd.Series(idx, index=idx).groupby([iso.year, iso.week]).last()
    return pd.DatetimeIndex(list(s))


def signals(F, P):
    f7 = F.rolling(7, min_periods=4).mean() * 365
    f30 = F.rolling(30, min_periods=15).mean() * 365
    out = {
        "fund7": f7,
        "fund30": f30,
        "fund_chg": f7 - F.rolling(60, min_periods=30).mean() * 365,
        "prem": P,
        "prem_z": (P - P.rolling(60, min_periods=30).mean()) / P.rolling(60, min_periods=30).std(),
        "prem_chg": P - P.rolling(7, min_periods=4).mean(),
    }
    return out


def ic_table(sig: pd.DataFrame, O: pd.DataFrame, dates, horizon=7):
    rows = []
    for i, d in enumerate(dates[:-1]):
        if d not in sig.index or d not in O.index:
            continue
        pos = O.index.get_loc(d)
        if pos + 1 + horizon >= len(O.index):
            continue
        fwd = O.iloc[pos + 1 + horizon] / O.iloc[pos + 1] - 1.0
        s = sig.loc[d]
        j = pd.concat([s.rename("s"), fwd.rename("f")], axis=1).dropna()
        if len(j) < 8:
            continue
        ic = j.s.corr(j.f, method="spearman")
        rows.append(dict(date=d, ic=ic, n=len(j)))
    return pd.DataFrame(rows).set_index("date")


def long_short(sig: pd.DataFrame, O: pd.DataFrame, dates, q=0.25, horizon=7,
               fee=0.0014):
    """Short the top-funding quantile, long the bottom, equal notional."""
    rets, turn = [], []
    prev = set()
    for d in dates[:-1]:
        if d not in sig.index or d not in O.index:
            continue
        pos = O.index.get_loc(d)
        if pos + 1 + horizon >= len(O.index):
            continue
        s = sig.loc[d].dropna()
        if len(s) < 10:
            continue
        hi = s.nlargest(max(2, int(len(s) * q))).index
        lo = s.nsmallest(max(2, int(len(s) * q))).index
        r = O.iloc[pos + 1 + horizon] / O.iloc[pos + 1] - 1.0
        r = r.reindex(list(hi) + list(lo))
        if r.isna().any():
            r = r.dropna()
            hi2 = [c for c in hi if c in r.index]
            lo2 = [c for c in lo if c in r.index]
            if not hi2 or not lo2:
                continue
            hi, lo = hi2, lo2
            r = O.iloc[pos + 1 + horizon] / O.iloc[pos + 1] - 1.0
        gross = (-r[hi].mean() + r[lo].mean())
        # turnover: fraction of names replaced
        cur = set(hi) | set(lo)
        t = len(cur ^ prev) / max(len(cur | prev), 1) if prev else 1.0
        prev = cur
        rets.append(gross - t * fee)
        turn.append(t)
    s = pd.Series(rets, index=[d for d in dates[:-1] if d in sig.index][: len(rets)])
    return s, np.mean(turn) if turn else np.nan


def ic_stats(t: pd.DataFrame, name: str) -> dict:
    x = t.ic.dropna()
    if len(x) < 30:
        return dict(name=name, n=len(x))
    tstat = x.mean() / (x.std() / np.sqrt(len(x)))
    h = len(x) // 2
    return dict(name=name, n=len(x), ic=x.mean(), t=tstat,
                pos_years=int((x.groupby(x.index.year).mean() > 0).sum()),
                years=x.index.year.nunique(),
                h1=x.iloc[:h].mean(), h2=x.iloc[h:].mean(),
                ir=x.mean() / x.std() * np.sqrt(52))


def main():
    F, P, O, C = panels()
    print("universe", len(F.columns), "days", len(F), F.index.min().date(), "->", F.index.max().date())
    sigs = signals(F, P)
    dates = weekly_grid(F.index)
    print("weekly decision points:", len(dates))

    rows = []
    for nm, s in sigs.items():
        t = ic_table(s, O, dates)
        rows.append(ic_stats(t, nm))
    d = pd.DataFrame(rows)
    print("\n===== rank IC vs next-week return =====")
    print(d.round(3).to_string(index=False))

    # year-by-year for the best candidate, to see if it is one regime
    for nm in ("fund7", "fund30", "prem_z"):
        t = ic_table(sigs[nm], O, dates)
        by = t.ic.groupby(t.index.year).agg(["mean", "size"])
        print(f"\n  {nm} IC by year:")
        print(by.round(3).T.to_string())

    # long-short on the strongest
    print("\n===== long low-funding / short high-funding, weekly =====")
    for nm in ("fund7", "fund30", "prem_z", "prem"):
        s, tv = long_short(sigs[nm], O, dates)
        if len(s) < 30:
            continue
        eq = (1 + s).cumprod()
        yrs = len(s) / 52
        dd = eq / eq.cummax() - 1
        h = len(s) // 2
        print(f"  {nm:8s} n={len(s):3d} ann {(eq.iloc[-1]**(1/yrs)-1)*100:6.1f}%  "
              f"vol {s.std()*np.sqrt(52)*100:5.1f}%  S {s.mean()/s.std()*np.sqrt(52):5.2f}  "
              f"MDD {dd.min()*100:6.1f}%  turn {tv:.2f}  "
              f"H1 {s.iloc[:h].mean()/s.iloc[:h].std()*np.sqrt(52):5.2f} "
              f"H2 {s.iloc[h:].mean()/s.iloc[h:].std()*np.sqrt(52):5.2f}")
    return F, P, O, C, sigs, dates


if __name__ == "__main__":
    main()
