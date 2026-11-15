"""Direction filter for the new (non-OHLCV) data.

Rule established last round: a feature is only worth a backtest if it predicts
the SIGN of the next bar with AUC > 0.52, and does so in BOTH halves of the
sample independently. Everything derived from OHLCV scored 0.486-0.502.

Features here come from open interest, top-trader positioning and taker flow --
i.e. actual positioning data, not price transforms.

Two bar sizes are tested because they answer different questions:
  1h  -> more samples, better for detecting a weak but real edge
  1d  -> the horizon the live strategy actually trades
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).resolve().parent / "data"
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)


# ---------------------------------------------------------------- statistics
def auc(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    """Mann-Whitney AUC of x separating y in {0,1}. 0.5 = no information."""
    m = x.notna() & y.notna()
    xv, yv = x[m].to_numpy(float), y[m].to_numpy(int)
    n1 = int(yv.sum())
    n0 = len(yv) - n1
    if n1 < 30 or n0 < 30:
        return np.nan, len(yv)
    r = pd.Series(xv).rank().to_numpy()
    return float((r[yv == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)), len(yv)


def block_boot_auc(x: pd.Series, y: pd.Series, block: int = 48, n: int = 200,
                   seed: int = 7) -> tuple[float, float]:
    """95% CI of AUC under a moving-block bootstrap (respects autocorrelation)."""
    m = x.notna() & y.notna()
    xv, yv = x[m].to_numpy(float), y[m].to_numpy(int)
    N = len(xv)
    if N < 500:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(N / block))
    out = []
    for _ in range(n):
        starts = rng.integers(0, N - block, nb)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:N]
        xs, ys = xv[idx], yv[idx]
        n1 = ys.sum()
        if n1 < 30 or (N - n1) < 30:
            continue
        rr = pd.Series(xs).rank().to_numpy()
        out.append((rr[ys == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (N - n1)))
    if not out:
        return np.nan, np.nan
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def segments(x: pd.Series, y: pd.Series, k: int = 8) -> list[float]:
    m = x.notna() & y.notna()
    x, y = x[m], y[m]
    out, edges = [], np.linspace(0, len(x), k + 1).astype(int)
    for i in range(k):
        a, b = edges[i], edges[i + 1]
        v, _ = auc(x.iloc[a:b], y.iloc[a:b])
        out.append(round(v, 3))
    return out


def screen(df: pd.DataFrame, feats: list[str], label: str, tag: str,
           block: int = 48) -> pd.DataFrame:
    y = df[label]
    half = df.index[len(df) // 2]
    rows = []
    for f in feats:
        if f not in df:
            continue
        a, n = auc(df[f], y)
        a1, _ = auc(df.loc[:half, f], y.loc[:half])
        a2, _ = auc(df.loc[half:, f], y.loc[half:])
        lo, hi = block_boot_auc(df[f], y, block=block)
        sg = segments(df[f], y, 8)
        rows.append(dict(feat=f, auc=a, h1=a1, h2=a2, lo=lo, hi=hi,
                         seg_min=min(sg), seg_max=max(sg),
                         both_up=(a1 > 0.51) and (a2 > 0.51),
                         both_dn=(a1 < 0.49) and (a2 < 0.49), n=n))
    t = pd.DataFrame(rows).sort_values("auc", ascending=False)
    print(f"\n===== {tag}: AUC on sign of next bar (label={label}) =====")
    print(t.round(4).to_string(index=False))
    return t


# ------------------------------------------------------------------- loading
def load_hourly(sym: str) -> pd.DataFrame:
    k = pd.read_parquet(D / "perp" / f"k1h_{sym}.parquet").set_index("dt").sort_index()
    k = k[["open", "high", "low", "close", "volume", "quote_volume", "trades"]]
    # taker buy volume from the raw monthly CSVs
    raw = sorted((D / "perp").glob(f"{sym}-klines-*.csv"))
    tb = []
    for p in raw:
        d = pd.read_csv(p, usecols=["open_time", "taker_buy_base", "volume"])
        tb.append(d)
    tb = pd.concat(tb, ignore_index=True)
    tb["ts"] = pd.to_datetime(tb["open_time"], unit="ms", utc=True)
    tb = tb.drop_duplicates("ts").set_index("ts").sort_index()
    k["taker_buy"] = tb["taker_buy_base"].reindex(k.index)
    k["taker_imb"] = k["taker_buy"] / k["volume"] - 0.5

    m = pd.read_parquet(D / "metrics" / f"{sym}-metrics-5m.parquet")
    m = m.resample("1h").last()
    j = k.join(m, how="left")
    return j


def add_feats(d: pd.DataFrame, sym: str, ppd: int = 24) -> pd.DataFrame:
    """ppd = bars per day, so every window is expressed in days."""
    d = d.copy()
    if "taker_imb" not in d and {"taker_buy", "volume"} <= set(d.columns):
        d["taker_imb"] = d["taker_buy"] / d["volume"] - 0.5
    oi = d["sum_open_interest"]
    px = d["close"]
    W = 7 * ppd
    mn = max(4, W // 4)

    def z(s, w=W, m=None):
        m = m or max(4, w // 4)
        return (s - s.rolling(w, min_periods=m).mean()) / s.rolling(w, min_periods=m).std()

    # --- OI dynamics
    d["oi_r1"] = oi.pct_change(1)
    d["oi_r4"] = oi.pct_change(ppd // 6 if ppd >= 6 else 1)
    d["oi_r24"] = oi.pct_change(ppd)
    d["oi_r72"] = oi.pct_change(3 * ppd)
    d["oi_z"] = z(oi)
    d["oi_chg_z"] = z(d["oi_r4"])

    # --- OI / price divergence: who is opening?
    # price up + OI up  = new longs (trend fuel)
    # price up + OI down= short covering (weak)
    r24 = px.pct_change(ppd)
    d["px_r24"] = r24
    d["div24"] = d["oi_r24"] - r24
    d["div_sign"] = np.sign(r24) * np.sign(d["oi_r24"])

    # --- taker aggression
    d["taker_z"] = z(d["taker_imb"])
    d["taker_4"] = d["taker_imb"].rolling(max(2, ppd // 6)).mean()
    d["taker_24"] = d["taker_imb"].rolling(ppd).mean()

    # --- top trader positioning (levels are slow; changes are the signal)
    for c, nm in [("count_toptrader_long_short_ratio", "tlr_cnt"),
                  ("sum_toptrader_long_short_ratio", "tlr_sum"),
                  ("count_long_short_ratio", "lr_cnt")]:
        s = d[c]
        d[nm + "_z"] = z(s)
        d[nm + "_r24"] = s.pct_change(ppd)

    d["tk_ls"] = d["sum_taker_long_short_vol_ratio"]
    d["tk_ls_z"] = z(d["tk_ls"])

    # --- funding as a change rate, not a level (level was already used)
    if (D / "perp" / "fnd_BTCUSDT.parquet").exists() and sym == "BTCUSDT":
        fnd = pd.read_parquet(D / "perp" / "fnd_BTCUSDT.parquet")
        fnd = fnd.set_index(pd.to_datetime(fnd["dt"], utc=True)).sort_index()
        f = fnd["last_funding_rate"].resample("1h").ffill()
        d["fund"] = f.reindex(d.index, method="ffill")
        d["fund_chg"] = d["fund"].diff(ppd)          # one day of funding drift
        d["fund_z"] = z(d["fund"], 30 * ppd)

    # --- realised vol (control: should predict |r|, not sign)
    d["rv24"] = d["close"].pct_change().rolling(ppd).std()
    return d


def main():
    for sym in ["BTCUSDT", "ETHUSDT"]:
        mp = D / "metrics" / f"{sym}-metrics-5m.parquet"
        if not mp.exists():
            print(f"{sym}: metrics missing, skip")
            continue
        d = load_hourly(sym)
        d = add_feats(d, sym)
        d["fwd"] = d["close"].shift(-1) / d["close"] - 1.0
        d["dir"] = (d["fwd"] > 0).astype(int)
        d["big"] = (d["fwd"].abs() > d["fwd"].abs().rolling(720, min_periods=240).median()).astype(int)

        feats = [c for c in d.columns if c.endswith(("_z", "_r1", "_r4", "_r24", "_r72",
                                                    "_chg", "imb", "taker_4", "taker_24",
                                                    "div24", "div_sign", "rv24", "tk_ls"))]
        feats = [c for c in feats if c not in ("px_r24",)]
        d = d.loc[d.index >= pd.Timestamp("2020-02-01", tz="UTC")]
        print(f"\n########## {sym}  n={len(d)}  {d.index.min()} -> {d.index.max()}")
        screen(d, feats, "dir", f"{sym} 1h", block=48)

        # daily aggregation, the horizon the real strategy trades
        dd = d.resample("1D").agg({
            "open": "first", "high": "max", "low": "min", "close": "last",
            "volume": "sum", "quote_volume": "sum", "trades": "sum",
            "taker_buy": "sum", "sum_open_interest": "last",
            "count_toptrader_long_short_ratio": "last",
            "sum_toptrader_long_short_ratio": "last",
            "count_long_short_ratio": "last",
            "sum_taker_long_short_vol_ratio": "last",
            "fund": "last", "tk_ls": "last",
        }).dropna(subset=["close"])
        dd = add_feats(dd, sym, ppd=1)
        dd["fwd"] = dd["close"].shift(-1) / dd["close"] - 1.0
        dd["dir"] = (dd["fwd"] > 0).astype(int)
        dd = dd.loc[dd.index >= pd.Timestamp("2020-03-01", tz="UTC")]
        screen(dd, feats, "dir", f"{sym} 1d", block=20)


if __name__ == "__main__":
    main()
