"""Research harness: daily TSMOM / cross-sectional momentum on Binance majors.

Execution convention: signal from close of day t-1, filled at open of day t,
held to open of day t+1. Costs charged on turnover at `cost_side` per unit.
Cash earns `rf` annualised when not invested.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).resolve().parent / "data"
BPY = 365


# ---------------------------------------------------------------- data
def load_panel(drop=("LUNAUSDT", "FTTUSDT")):
    """LUNA: old token collapse spliced onto the new token (82 -> 0.0003 -> 6.5).
    FTT: 311-day trading halt with a frozen price. Both are unusable."""
    df = pd.read_parquet(D / "daily" / "daily_panel.parquet")
    if drop:
        df = df[~df["symbol"].isin(drop)]
    C = df.pivot_table(index="dt", columns="symbol", values="close").sort_index()
    O = df.pivot_table(index="dt", columns="symbol", values="open").sort_index()
    H = df.pivot_table(index="dt", columns="symbol", values="high").sort_index()
    L = df.pivot_table(index="dt", columns="symbol", values="low").sort_index()
    V = df.pivot_table(index="dt", columns="symbol", values="quote_volume").sort_index()
    idx = C.index
    C = C.reindex(idx).ffill(limit=3)
    O = O.reindex(idx).ffill(limit=3)
    H = H.reindex(idx).ffill(limit=3)
    L = L.reindex(idx).ffill(limit=3)
    V = V.reindex(idx)
    return C, O, H, L, V


def zscore(C: pd.DataFrame, lookbacks=(20, 40, 60, 90)) -> pd.DataFrame:
    r = C.pct_change()
    parts = []
    for L in lookbacks:
        v = r.rolling(L).std() * np.sqrt(L)
        parts.append(((C / C.shift(L) - 1) / v.replace(0, np.nan)).clip(-3, 3))
    return sum(parts) / len(parts)


# ---------------------------------------------------------------- weights
def weights_tsmom(z, enter=0.3, exit_=0.0, topk=None, liq=None, vol=None,
                  vol_target=None, max_gross=1.0, allow_short=False):
    """Per-asset hysteresis state machine, optional cross-sectional top-K, inverse-vol weights."""
    Z = z.to_numpy()
    ok = np.ones_like(Z, dtype=bool) if liq is None else liq.to_numpy()
    state = np.zeros(Z.shape[1])
    states = np.zeros_like(Z)
    for t in range(Z.shape[0]):
        row = Z[t]
        good = ok[t] & ~np.isnan(row)
        st = np.where(good & (row > enter) & (state <= 0), 1.0, state)
        if allow_short:
            st = np.where(good & (row < -enter) & (state >= 0), -1.0, st)
        st = np.where(good & (row < exit_) & (st > 0), 0.0, st)
        st = np.where(good & (row > -exit_) & (st < 0), 0.0, st)
        st = np.where(~good, 0.0, st)
        state = st
        states[t] = st

    W = pd.DataFrame(states, index=z.index, columns=z.columns)
    if topk is not None:
        rk = z.where(W > 0).rank(axis=1, ascending=False, method="first")
        W = W.where(rk <= topk, 0.0)
        if allow_short:
            rk_s = z.where(W < 0).rank(axis=1, ascending=True, method="first")
            W = W.where((W >= 0) | (rk_s <= topk), 0.0)

    iw = 1.0 / vol if vol is not None else pd.DataFrame(1.0, index=z.index, columns=z.columns)
    W = (W * iw).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    gross = W.abs().sum(axis=1).replace(0, np.nan)
    W = W.div(gross, axis=0).fillna(0.0) * max_gross
    return W


def weights_tsmom_trail(z, C, enter=0.3, exit_=0.0, topk=None, trail=None, atr=None,
                        vol=None, max_gross=1.0):
    """Hysteresis entry + optional trailing stop from the highest close since entry."""
    Z = z.to_numpy()
    P = C.to_numpy()
    A = None if atr is None else atr.to_numpy()
    state = np.zeros(Z.shape[1])
    peak = np.zeros(Z.shape[1])
    states = np.zeros_like(Z)
    for t in range(Z.shape[0]):
        row, px = Z[t], P[t]
        good = ~np.isnan(row) & ~np.isnan(px)
        entered = good & (row > enter) & (state <= 0)
        state = np.where(entered, 1.0, state)
        peak = np.where(entered | ((state > 0) & (px > peak)), px, peak)
        state = np.where(good & (row < exit_) & (state > 0), 0.0, state)
        if trail is not None:
            stop = peak * (1 - trail)
            state = np.where((state > 0) & good & (px < stop), 0.0, state)
        if A is not None:
            stop = peak - 3.0 * A[t]
            state = np.where((state > 0) & good & (px < stop), 0.0, state)
        state = np.where(~good, 0.0, state)
        states[t] = state
    W = pd.DataFrame(states, index=z.index, columns=z.columns)
    if topk is not None:
        rk = z.where(W > 0).rank(axis=1, ascending=False, method="first")
        W = W.where(rk <= topk, 0.0)
    iw = 1.0 / vol if vol is not None else pd.DataFrame(1.0, index=z.index, columns=z.columns)
    W = (W * iw).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    gross = W.abs().sum(axis=1).replace(0, np.nan)
    return W.div(gross, axis=0).fillna(0.0) * max_gross


def backtest(C, O, W, cost_side=0.0010, rf=0.0, vol_target=None, target_vol=None,
             vol_win=60, max_lev=1.0):
    fwd = O.shift(-1) / O - 1
    if vol_target is not None:
        raw = (W.shift(1) * fwd).sum(axis=1)
        pv = raw.rolling(vol_win).std() * np.sqrt(BPY)
        sc = (vol_target / pv.shift(1)).clip(upper=max_lev).fillna(1.0)
        W = W.mul(sc, axis=0)
        W = W.clip(-max_lev, max_lev)
    gross_ret = (W.shift(1) * fwd).sum(axis=1)
    turn = (W - W.shift(1)).abs().sum(axis=1)
    expo = W.abs().sum(axis=1)
    cash = 1.0 - expo
    ret = gross_ret + cash * (rf / BPY) - turn * cost_side
    ret = ret.iloc[1:]
    eq = (1 + ret).cumprod()
    yrs = len(ret) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    out = dict(
        total=eq.iloc[-1] - 1,
        cagr=eq.iloc[-1] ** (1 / yrs) - 1,
        vol=ret.std() * np.sqrt(BPY),
        sharpe=ret.mean() / ret.std() * np.sqrt(BPY) if ret.std() else np.nan,
        mdd=mdd,
        calmar=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(mdd) if mdd else np.nan,
        expo=expo.iloc[:-1].mean(),
        turn_pa=turn.iloc[:-1].mean() * BPY,
        cost_pa=(turn * cost_side).iloc[:-1].mean() * BPY,
        gross_pa=gross_ret.iloc[:-1].mean() * BPY,
    )
    return out, eq, ret, W


def evaluate(W, C, O, cost=0.0010, rf=0.0, start="2020-06-01", vol_target=None, max_lev=1.0):
    m, eq, ret, W2 = backtest(C, O, W, cost_side=cost, rf=rf, vol_target=vol_target, max_lev=max_lev)
    ret = ret.loc[ret.index >= start]
    eq = (1 + ret).cumprod()
    yrs = len(ret) / BPY
    mdd = (eq / eq.cummax() - 1).min()
    turn = (W2 - W2.shift(1)).abs().sum(axis=1).loc[start:]
    out = dict(
        total=eq.iloc[-1] - 1, cagr=eq.iloc[-1] ** (1 / yrs) - 1,
        vol=ret.std() * np.sqrt(BPY),
        sharpe=ret.mean() / ret.std() * np.sqrt(BPY),
        mdd=mdd, calmar=(eq.iloc[-1] ** (1 / yrs) - 1) / abs(mdd) if mdd else np.nan,
        expo=W2.abs().sum(axis=1).loc[start:].mean(),
        turn_pa=turn.mean() * BPY, cost_pa=turn.mean() * cost * BPY,
    )
    return out, eq, ret, W2


def yearly(ret):
    return ((1 + ret).groupby(ret.index.year).prod() - 1) * 100


def fmt(df, cols=None, pct=("total", "cagr", "vol", "mdd", "cost_pa", "gross_pa", "expo")):
    cols = cols or [c for c in df.columns if c != "turn_pa"]
    d = df.copy()
    for c in d.columns:
        if c in pct:
            d[c] = (d[c] * 100).round(1)
        elif c in ("sharpe", "calmar", "turn_pa"):
            d[c] = d[c].round(2)
    return d[cols].to_string(index=False)
