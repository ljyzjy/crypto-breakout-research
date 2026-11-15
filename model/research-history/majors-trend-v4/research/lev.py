"""Perp engine: funding, liquidation, long/short, and an effective-leverage schedule.

Margin modes behave differently and this matters a lot:

  isolated -- each position posts notional/L as margin and dies at 1/L - mm. The exchange
              multiple you pick IS the liquidation distance; position size does not help.
  cross    -- the whole account backs the position, so it dies when equity <= mm x notional,
              i.e. at 1/A - mm where A = notional/equity. The 40x setting is only a cap;
              3x and 40x are identical when A = 2.

Everything here is written in terms of A = notional / equity ("effective leverage"),
because that is what sets both return and liquidation distance.

Accounting: units of the asset plus cash. Equity = cash + sum(units * price).
Rebalance at the open, charge funding on the notional carried, check liquidation on the
intraday extreme, mark to close.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).resolve().parent / "data"
BPY = 365
MM = 0.004       # tier-1 maintenance margin rate, BTCUSDT perp
FEE = 0.0004     # taker each side
LIQ_FEE = 0.005  # extra penalty when force-closed


# ------------------------------------------------------------------ data
def load_perp(symbols=("BTCUSDT",)):
    """Daily OHLC aggregated from the 1h perp archive, plus the daily funding sum.

    Aggregating from 1h (not from the spot panel) keeps the perp's own prices, which
    differ from spot and are what actually triggers liquidation.
    """
    cols = {}
    for sym in symbols:
        k = pd.read_parquet(D / "perp" / f"k1h_{sym}.parquet")
        k["dt"] = pd.to_datetime(k["dt"], utc=True)
        k["day"] = k["dt"].dt.normalize()
        g = k.groupby("day").agg(open=("open", "first"), high=("high", "max"),
                                 low=("low", "min"), close=("close", "last"))
        for c in ("open", "high", "low", "close"):
            cols.setdefault(c, {})[sym] = g[c]
    idx = None
    for c in cols.values():
        for s in c.values():
            idx = s.index if idx is None else idx.union(s.index)
    O = pd.DataFrame({s: v.reindex(idx) for s, v in cols["open"].items()})
    H = pd.DataFrame({s: v.reindex(idx) for s, v in cols["high"].items()})
    L = pd.DataFrame({s: v.reindex(idx) for s, v in cols["low"].items()})
    C = pd.DataFrame({s: v.reindex(idx) for s, v in cols["close"].items()})

    fr = {}
    for sym in symbols:
        p = D / "perp" / f"fnd_{sym}.parquet"
        if not p.exists():
            fr[sym] = pd.Series(0.0, index=idx)
            continue
        f = pd.read_parquet(p)
        f["dt"] = pd.to_datetime(f["dt"], utc=True)
        f["day"] = f["dt"].dt.normalize()
        fr[sym] = f.groupby("day")["last_funding_rate"].sum().reindex(idx).fillna(0.0)
    F = pd.DataFrame(fr)[list(symbols)]
    return C, O, H, L, F


# ------------------------------------------------------------------ signals
def zscore(C, lookbacks=(20, 40, 60, 90)):
    r = C.pct_change()
    parts = []
    for n in lookbacks:
        v = r.rolling(n).std() * np.sqrt(n)
        parts.append(((C / C.shift(n) - 1) / v.replace(0, np.nan)).clip(-3, 3))
    return sum(parts) / len(parts)


def signal_weight(z, vol, enter=0.20, target_vol=0.40, allow_short=False):
    """Direction x vol budget, expressed as notional per 1 unit of equity at A=1."""
    scale = (target_vol / vol).clip(upper=1.0)
    long_w = z.clip(lower=0, upper=1.0) * scale
    long_w = long_w.where(z > enter, 0.0)
    if not allow_short:
        return long_w.fillna(0.0)
    short_w = (-z).clip(lower=0, upper=1.0) * scale
    short_w = short_w.where(z < -enter, 0.0)
    return (long_w.fillna(0.0) - short_w.fillna(0.0))


# ------------------------------------------------------------------ engine
def simulate(W, A, C, O, H, L, funding=None, mm=MM, fee=FEE, liq=True,
             start="2020-01-01", reenter=True, lag=1, spot_base=False):
    """W: signed target notional per unit of equity before leverage.
       A: effective leverage (notional/equity). Scalar or Series.

    `lag` shifts the signal forward so a weight built from the close of day t-1 is
    filled at the open of day t. Never use lag=0 on real data.
    """
    idx = C.index
    O, H, L, C = (x.reindex(idx) for x in (O, H, L, C))
    W = W.reindex(idx).fillna(0.0).shift(lag).fillna(0.0).to_numpy()
    n, k = W.shape
    if isinstance(A, pd.Series):
        a = A.reindex(idx).ffill().shift(lag).fillna(1.0).to_numpy()
    else:
        a = np.full(n, float(A))
    o, hi, lo, cl = O.to_numpy(), H.to_numpy(), L.to_numpy(), C.to_numpy()
    fr = (funding.reindex(idx).fillna(0.0).to_numpy()
          if funding is not None else np.zeros((n, k)))
    cols = list(C.columns)

    units = np.zeros(k)
    cash = 1.0
    curve = np.full(n, np.nan)
    curve[0] = 1.0
    liq_log, blocked_until = [], -1
    fee_frac = fund_frac = 0.0
    expo_path = np.zeros(n)

    for t in range(1, n):
        px = o[t]
        notional = units * px
        equity = cash + notional.sum()
        if equity <= 1e-3:
            curve[t] = max(equity, 0.0)
            curve[t:] = curve[t]
            break

        # ---------- rebalance at the open
        tgt = W[t] * a[t] * equity
        if t < blocked_until:
            tgt = np.zeros(k)
        d_units = (tgt - notional) / px
        cost = (np.abs(d_units) * px).sum() * fee
        cash -= (d_units * px).sum() + cost
        units = units + d_units
        fee_frac += cost / max(equity, 1e-12)
        expo_path[t] = np.abs(units * px).sum() / max(equity - cost, 1e-12)

        # ---------- funding on the notional carried through the day
        # spot_base: the first 1x of a long can be held in spot, which pays no funding.
        # Only the levered excess has to be a perp, so only that part is charged.
        # Single-asset reading of "1x of equity"; for a book it would need a per-asset cap.
        notional_now = units * px
        if spot_base:
            eq_now = max(equity, 1e-12)
            # only the long side can be held in spot; a short is always a perp
            lng = np.maximum(notional_now, 0.0)
            sht = np.minimum(notional_now, 0.0)
            excess_long = np.maximum(lng - eq_now, 0.0)
            paid = float(((excess_long + sht) * fr[t]).sum())
        else:
            paid = float((notional_now * fr[t]).sum())
        cash -= paid
        fund_frac += paid / max(equity, 1e-12)

        # ---------- liquidation on the intraday extreme
        if liq and np.any(units != 0):
            worst_px = np.where(units > 0, lo[t], hi[t])
            gross = float(np.abs(units * worst_px).sum())
            eq_worst = cash + (units * worst_px).sum()
            if gross > 0 and eq_worst <= mm * gross + 1e-12:
                realised = max(eq_worst, 0.0) * (1.0 - LIQ_FEE)
                j = int(np.argmax(np.abs(units)))
                liq_log.append(dict(dt=idx[t], A=float(a[t]),
                                    move=float(worst_px[j] / px[j] - 1.0),
                                    eq_before=float(equity), eq_after=float(realised)))
                units = np.zeros(k)
                cash = realised
                curve[t] = cash
                blocked_until = t + (0 if reenter else 10 ** 9)
                continue

        # ---------- mark to close
        curve[t] = cash + (units * cl[t]).sum()

    curve = pd.Series(curve, index=idx).ffill().fillna(1.0)
    ret = curve.pct_change().fillna(0.0)
    seg = ret.loc[start:].iloc[1:]
    eq = (1 + seg).cumprod()
    eq = eq / eq.iloc[0]
    yrs = max(len(seg) / BPY, 1e-9)
    cagr = float(eq.iloc[-1] ** (1 / yrs) - 1) if eq.iloc[-1] > 0 else -1.0
    mdd = float((eq / eq.cummax() - 1).min())
    m = dict(total=float(eq.iloc[-1] - 1), cagr=cagr,
             vol=float(seg.std() * np.sqrt(BPY)),
             sharpe=float(seg.mean() / seg.std() * np.sqrt(BPY)) if seg.std() else np.nan,
             mdd=mdd, calmar=float(cagr / abs(mdd)) if mdd else np.nan,
             liq=len(liq_log), fee_pa=float(fee_frac / yrs),
             fund_pa=float(fund_frac / yrs),
             expo=float(pd.Series(expo_path, index=idx).loc[start:].mean()))
    return m, eq, seg, liq_log
