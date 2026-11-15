"""Cross-sectional breadth as a regime gate for the BTC trend.

Everything tested so far was a transformation of BTC's own OHLCV, and the
project's conclusion was that such transformations carry no directional
information. Breadth is different in kind: it is information about the rest of
the market, and it is cheap to compute from the 21-coin daily panel.

Screened first as a predictor (rank IC vs BTC's next-week return), then as a
gate on V4, then against the matched-exposure control that killed the earlier
leverage ideas: a gate that merely reduces exposure must beat a constant
exposure of the same average, otherwise it is just de-risking.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev

pd.set_option("display.width", 240)
BPY = 365
S = "BTCUSDT"
BAD = {"LUNAUSDT", "FTTUSDT"}


def panel():
    d = pd.read_parquet("data/daily/daily_panel.parquet")
    d["dt"] = pd.to_datetime(d["dt"], utc=True)
    C = d.pivot_table(index="dt", columns="symbol", values="close", aggfunc="last")
    return C[[c for c in C.columns if c not in BAD]].sort_index()


def features(C: pd.DataFrame) -> pd.DataFrame:
    r = C.pct_change()
    out = {}
    for n in (50, 200):
        out[f"breadth{n}"] = (C > C.rolling(n, min_periods=n // 2).mean()).mean(axis=1)
    out["breadth_chg"] = out["breadth200"] - out["breadth200"].shift(20)
    alt = (C / C.iloc[0]).mean(axis=1)
    out["altbtc_mom"] = (alt / C[S]).pct_change(30)
    r30 = C / C.shift(30) - 1
    out["disp"] = r30.std(axis=1)
    # co-movement: average correlation of each coin's daily return with the
    # equal-weight index. Cheaper than the full pairwise matrix and equivalent
    # in spirit: high means the market moves as one.
    idx = r.mean(axis=1)
    out["avgcorr"] = pd.concat(
        [r[c].rolling(60, min_periods=30).corr(idx) for c in r.columns], axis=1).mean(axis=1)
    out["trend_strength"] = (C[S] / C[S].rolling(200, min_periods=100).mean() - 1)
    out["vol_regime"] = r[S].rolling(30, min_periods=15).std() / r[S].rolling(180, min_periods=90).std()
    return pd.DataFrame(out)


def weekly_pairs(sig: pd.Series, px: pd.Series, horizon=7):
    idx = px.index
    iso = idx.isocalendar()
    dates = pd.DatetimeIndex(list(pd.Series(idx, index=idx).groupby([iso.year, iso.week]).last()))
    rows = []
    for d in dates[:-1]:
        if d not in sig.index:
            continue
        pos = idx.get_loc(d)
        if pos + 1 + horizon >= len(idx):
            continue
        fwd = px.iloc[pos + 1 + horizon] / px.iloc[pos + 1] - 1
        s = sig.loc[d]
        if pd.notna(s) and pd.notna(fwd):
            rows.append(dict(date=d, s=float(s), f=float(fwd)))
    return pd.DataFrame(rows).set_index("date") if rows else None


def screen(C):
    F = features(C)
    print("===== Friday-close feature vs BTC's next-week return =====")
    rows = []
    for c in F.columns:
        t = weekly_pairs(F[c], C[S])
        if t is None or len(t) < 60:
            continue
        ic = t.s.corr(t.f, method="spearman")
        h = len(t) // 2
        ic1 = t.iloc[:h].s.corr(t.iloc[:h].f, method="spearman")
        ic2 = t.iloc[h:].s.corr(t.iloc[h:].f, method="spearman")
        q = pd.qcut(t.s, 3, labels=False, duplicates="drop")
        hit = t.groupby(q).f.mean() * 100
        rows.append(dict(feat=c, n=len(t), ic=ic, ic_h1=ic1, ic_h2=ic2,
                         low=hit.get(0, np.nan), mid=hit.get(1, np.nan),
                         high=hit.get(2, np.nan),
                         spread=hit.get(2, np.nan) - hit.get(0, np.nan)))
    d = pd.DataFrame(rows).sort_values("spread", ascending=False)
    print(d.round(3).to_string(index=False))
    return F


def v4_weights(C2, O, H, L, Fd):
    c = C2[S]
    r = c.pct_change()
    vol = (r.rolling(60, min_periods=30).std() * np.sqrt(BPY)).clip(lower=0.15)
    z = lev.zscore(C2)[S]
    px_dd = (c / c.rolling(365, min_periods=120).max() - 1.0)
    tgt = (0.40 / vol).clip(upper=1.0)
    long_w = (z.clip(lower=0, upper=1.0) * tgt).where(z > 0.20, 0.0)
    fnd = Fd[S]
    fq = fnd.rolling(365, min_periods=180).apply(lambda x: (x[-1] > x[:-1]).mean(), raw=True)
    short_w = ((-z).clip(lower=0, upper=1.0) * tgt).where((z < -0.20) & (fq > 0.40), 0.0)
    W = (long_w.fillna(0.0) - short_w.fillna(0.0)).to_frame(S)
    A = pd.Series(1.0, index=c.index)
    A = A.mask((vol < 0.60) & (px_dd > -0.20), 1.25)
    A = A.mask((vol < 0.45) & (px_dd > -0.10) & (z > 0.20), 1.75)
    return W, A.clip(1.0, 3.0)


def gate_test(F, C):
    C2, O, H, L, Fd = lev.load_perp((S,))
    W, A = v4_weights(C2, O, H, L, Fd)
    c = C2[S]
    rows = []

    def sim(Ax, label):
        m, eq, ret, liq = lev.simulate(W, Ax, C2, O, H, L, funding=Fd,
                                       liq=True, start="2020-06-01", spot_base=True)
        x = ret.loc["2020-06-01":]
        e = (1 + x).cumprod()
        yrs = len(x) / BPY
        dd = e / e.cummax() - 1
        h = len(x) // 2
        return dict(cfg=label,
                    expo=float((W[S].abs() * Ax).shift(1).loc["2020-06-01":].mean()),
                    cagr=(e.iloc[-1] ** (1 / yrs) - 1) * 100,
                    sharpe=x.mean() / x.std() * np.sqrt(BPY), mdd=dd.min() * 100,
                    calmar=(e.iloc[-1] ** (1 / yrs) - 1) / abs(dd.min()),
                    h1=x.iloc[:h].mean() / x.iloc[:h].std() * np.sqrt(BPY),
                    h2=x.iloc[h:].mean() / x.iloc[h:].std() * np.sqrt(BPY))

    base = sim(A, "V4 base")
    rows.append(base)
    base_expo = base["expo"]

    for feat, mode, thr in (("breadth200", "gt", 0.5), ("breadth200", "gt", 0.35),
                            ("breadth50", "gt", 0.5), ("trend_strength", "gt", 0.0),
                            ("disp", "z", 0.0), ("avgcorr", "z", 0.0)):
        s = F[feat].reindex(c.index).ffill()
        if mode == "z":
            zz = (s - s.rolling(365, min_periods=120).mean()) / s.rolling(365, min_periods=120).std()
            gate = (zz > thr).astype(float)
        else:
            gate = (s > thr).astype(float)
        gate = gate.shift(1).fillna(0.0)
        Ax = A * (0.5 + 0.5 * gate)
        m = sim(Ax, f"{feat}>{thr} gate 0.5-1.0")
        rows.append(m)
        rows.append(sim(A * (m["expo"] / base_expo), f"  matched const {m['expo']:.2f}x"))

    df = pd.DataFrame(rows)
    df["d_sharpe_vs_matched"] = np.nan
    for i, r in df.iterrows():
        if r.cfg.startswith("  matched"):
            df.loc[i, "d_sharpe_vs_matched"] = df.loc[i - 1, "sharpe"] - r.sharpe
    print("\n===== gate on V4, each with a matched constant-exposure control =====")
    print(df.round(2).to_string(index=False))


def main():
    C = panel()
    print("panel", C.shape, C.index.min().date(), "->", C.index.max().date())
    F = screen(C)
    gate_test(F, C)


if __name__ == "__main__":
    main()
