"""Does positioning data tell us WHEN trend-following works?

The direction test failed: after controlling for the past return, open interest and
taker flow had no residual predictive power (AUC 0.497 and 0.500). But "which way
does BTC go next hour" is not the question a trend follower needs answered. The
question is: given that the trend signal says long, is this a good long or a bad one?

So instead of predicting returns, condition the EXISTING strategy's daily P&L on
positioning regimes known at the previous close:

  oi_pct    open interest, percentile of the last 365 days (crowding)
  oi_chg30  OI change over 30 days (is leverage being added or removed)
  div30     OI change minus price change over 30 days (who is opening?)
  tk30      average taker buy imbalance over 30 days (persistent aggression)
  fund_pct  funding percentile (already known to matter for shorts)

Every feature is shifted by one day. Reported per tercile: the strategy's own daily
return, its Sharpe, and the hit rate -- because a conditioning variable is only
useful if it changes the strategy's payoff, not merely BTC's drift.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lev import D, load_perp, zscore

pd.set_option("display.width", 220)


def daily_positioning(sym="BTCUSDT") -> pd.DataFrame:
    m = pd.read_parquet(D / "metrics" / f"{sym}-metrics-5m.parquet")
    g = m.resample("1D").agg(
        oi=("sum_open_interest", "last"),
        oi_hi=("sum_open_interest", "max"),
        oi_lo=("sum_open_interest", "min"),
        tlr=("sum_toptrader_long_short_ratio", "last"),
        tlr_cnt=("count_toptrader_long_short_ratio", "last"),
        tk=("sum_taker_long_short_vol_ratio", "mean"),
    )
    return g


def build(sym="BTCUSDT"):
    C, O, H, L, F = load_perp([sym])
    c = C[sym]
    r = c.pct_change()
    vol = r.rolling(60).std() * np.sqrt(365)
    z = zscore(C)[sym]
    from lev import signal_weight
    W = signal_weight(z, vol, enter=0.20, target_vol=0.40)

    p = daily_positioning(sym).reindex(c.index)
    # 2022-03-07 / 2024-07-10 / 2024-07-12 report OI = 0 (feed outage). Left in place
    # they become inf after pct_change(30) and land in the top tercile, which is
    # exactly where the effect looked strongest -- so they must go.
    p["oi"] = p["oi"].where(p["oi"] > 0)
    p["tk"] = p["tk"].where(p["tk"] > 0)
    d = pd.DataFrame({"close": c, "ret": r, "vol": vol, "z": z, "w": W})
    d["oit"] = p["oi"]
    d["oi_pct"] = p["oi"].rolling(365, min_periods=120).rank(pct=True)
    d["oi_chg30"] = p["oi"] / p["oi"].shift(30) - 1
    d["px_chg30"] = c / c.shift(30) - 1
    d["div30"] = d["oi_chg30"] - d["px_chg30"]
    d["tk30"] = p["tk"].rolling(30).mean()
    d["tlr_chg30"] = p["tlr"] / p["tlr"].shift(30) - 1
    fund = F[sym] if sym in F else pd.Series(0.0, index=c.index)
    d["fund30"] = fund.rolling(30).sum()
    d["fund_pct"] = d["fund30"].rolling(365, min_periods=120).rank(pct=True)

    # strategy P&L at A=1: yesterday's notional times today's return
    d["pnl"] = d["w"].shift(1) * d["ret"]
    # BTC's own return on days the strategy was long (same days, so we can compare)
    d["pnl_hold"] = d["ret"]
    return d


def tercile(d, f, y="pnl", q=3, label=""):
    # f is lagged one day: oi_chg30 measured at t contains day t's own activity, and
    # pnl(t) already depends on yesterday's position, so using f(t) would be a
    # look-ahead -- OI rises on up days, and the strategy is long on up days.
    dt = d[[f, y, "w"]].copy()
    dt[f] = dt[f].shift(1)
    t = dt.dropna()
    if len(t) < 300 or t[f].nunique() < 10:
        print(f"{f}: not enough data")
        return None
    t["b"] = pd.qcut(t[f], q, labels=False, duplicates="drop")
    rows = []
    for b, g in t.groupby("b"):
        s = g[y]
        rows.append(dict(b=b, n=len(g), f_lo=g[f].min(), f_hi=g[f].max(),
                         ann=s.mean() * 365 * 100,
                         shp=s.mean() / s.std() * np.sqrt(365) if s.std() else np.nan,
                         win=(s > 0).mean() * 100,
                         expo=g["w"].mean() * 100))
    out = pd.DataFrame(rows).sort_values("b")
    out["t"] = [g[y].mean() / (g[y].std() / np.sqrt(len(g))) if len(g) > 2 and g[y].std() else np.nan
                for _, g in t.groupby("b")]
    print(f"\n----- strategy P&L by {f}.shift(1) tercile {label} -----")
    print(out.round(2).to_string(index=False))
    return out


def main():
    d = build("BTCUSDT")
    d = d.loc[d.index >= "2020-03-01"]
    print(f"n={len(d)}  {d.index.min().date()} -> {d.index.max().date()}")
    print(f"unconditional: ann={d.pnl.mean()*365*100:.1f}%  "
          f"sharpe={d.pnl.mean()/d.pnl.std()*np.sqrt(365):.2f}  "
          f"in-position days={(d.w>0).mean()*100:.1f}%")

    feats = ["oi_pct", "oi_chg30", "div30", "tk30", "tlr_chg30", "fund_pct"]
    half = d.index[len(d) // 2]
    for f in feats:
        tercile(d, f, "pnl")
        # split-half consistency of the top-vs-bottom tercile spread
        a = d.loc[:half]
        b = d.loc[half:]
        sa = tercile(a, f, "pnl", label="[1st half]")
        sb = tercile(b, f, "pnl", label="[2nd half]")
        if sa is not None and sb is not None and len(sa) == 3:
            print(f"    spread ann: full={sa.ann.iloc[-1]-sa.ann.iloc[0]:.0f}pp  "
                  f"1H={sa.ann.iloc[-1]-sa.ann.iloc[0]:.0f}pp  "
                  f"2H={sb.ann.iloc[-1]-sb.ann.iloc[0]:.0f}pp")

    # ---- only the days the strategy is actually long
    print("\n########## in-position days only ##########")
    pos = d[d["w"] > 0]
    print(f"n={len(pos)}  ann={pos.pnl.mean()*365*100:.1f}%  "
          f"sharpe={pos.pnl.mean()/pos.pnl.std()*np.sqrt(365):.2f}")
    for f in feats:
        tercile(pos, f, "pnl", label="[in position]")


if __name__ == "__main__":
    main()
