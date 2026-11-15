"""Structural variants on top of BtcTrendV2, 2018-2026 daily, spot only.

Execution: weight decided on close t, filled at open t+1 (W.shift(1) * O(t+1)/O(t)).
Cost 10bp per unit turnover, cash earns rf.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lab

BPY = 365
COST = 0.0010


# ------------------------------------------------------------------ data
def load_long(symbols=("BTCUSDT", "ETHUSDT")):
    main = pd.read_parquet(lab.D / "daily" / "daily_panel.parquet")
    early = pd.read_parquet(lab.D / "daily" / "early_panel.parquet")
    df = pd.concat([early, main[main.symbol.isin(symbols)]]).drop_duplicates(["dt", "symbol"])
    df = df[df.symbol.isin(symbols)]
    out = {}
    for col in ("close", "open", "high", "low"):
        p = df.pivot_table(index="dt", columns="symbol", values=col).sort_index()
        out[col] = p.ffill(limit=3)
    return out["close"], out["open"], out["high"], out["low"]


# ------------------------------------------------------------------ sizing helpers
def w_v2(z, vol, target=0.40, cap=1.0, zmax=1.0):
    """BtcTrendV2 sizing: linear in z, scaled by a vol budget, never above 100%."""
    scale = (target / vol).clip(upper=1.0)
    return (z.clip(lower=0, upper=zmax) * scale).fillna(0.0).clip(upper=cap)


def w_tanh(z, vol, target=0.40, cap=1.0, k=1.0):
    return (np.tanh(z.clip(lower=0) * k) * (target / vol).clip(upper=1.0)).fillna(0.0).clip(upper=cap)


def w_sqrt(z, vol, target=0.40, cap=1.0):
    return (np.sqrt(z.clip(lower=0, upper=4)) * (target / vol).clip(upper=1.0)).fillna(0.0).clip(upper=cap)


# ------------------------------------------------------------------ engine
def run(W, O, cost=COST, rf=0.0, start="2018-01-01", end=None):
    W = W.fillna(0.0)
    fwd = O.shift(-1) / O - 1
    fwd = fwd.reindex(columns=W.columns)
    gross = (W.shift(1) * fwd).sum(axis=1, min_count=1).fillna(0.0)
    turn = (W - W.shift(1)).abs().sum(axis=1).fillna(0.0)
    expo = W.abs().sum(axis=1)
    ret = gross + (1.0 - expo) * (rf / BPY) - turn * cost
    ret = ret.loc[start:end].iloc[1:]
    eq = (1 + ret).cumprod()
    yrs = len(ret) / BPY
    mdd = float((eq / eq.cummax() - 1).min())
    out = dict(
        total=float(eq.iloc[-1] - 1),
        cagr=float(eq.iloc[-1] ** (1 / yrs) - 1),
        vol=float(ret.std() * np.sqrt(BPY)),
        sharpe=float(ret.mean() / ret.std() * np.sqrt(BPY)),
        mdd=mdd,
        calmar=float((eq.iloc[-1] ** (1 / yrs) - 1) / abs(mdd)) if mdd else np.nan,
        expo=float(expo.loc[start:end].mean()),
        turn=float(turn.loc[start:end].mean() * BPY),
        cost_pa=float((turn * cost).loc[start:end].mean() * BPY),
        worst_y=float(lab.yearly(ret).min()),
    )
    return out, eq, ret


def row(name, W, O, **kw):
    m, eq, ret = run(W, O, **kw)
    m["cfg"] = name
    m["_ret"] = ret
    m["_eq"] = eq
    return m


def table(rows, cols=("cfg", "cagr", "sharpe", "mdd", "calmar", "vol", "expo", "turn", "cost_pa", "worst_y")):
    d = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
    for c in ("cagr", "mdd", "vol", "expo", "cost_pa", "worst_y"):
        d[c] = (d[c] * 100).round(1)
    d["sharpe"] = d["sharpe"].round(2)
    d["calmar"] = d["calmar"].round(2)
    d["turn"] = d["turn"].round(1)
    return d[list(cols)].to_string(index=False)


def ytab(rows):
    d = pd.DataFrame({r["cfg"]: lab.yearly(r["_ret"]).round(1) for r in rows})
    return d.to_string()
