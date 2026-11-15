"""Is the taker-flow reversal NEW information, or just the past return in disguise?

taker_imb(t) is measured inside bar t and is mechanically correlated with bar t's
return. Returns themselves mean-revert. So before celebrating an AUC of 0.473 we
have to show the flow adds something the price already does not contain -- price
is free, order flow costs a data subscription and a lot of engineering.

Three tests:
  1. horizon decay: over how many bars does the edge survive
  2. magnitude: is the decile spread larger than the round-trip cost
  3. control: 2-way sort on (past return, flow) -- does flow still separate
     inside a bucket of identical past returns?
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oi_1 import D, auc, add_feats, load_hourly

pd.set_option("display.width", 220)


def prep(sym="BTCUSDT"):
    d = load_hourly(sym)
    d = add_feats(d, sym, ppd=24)
    d = d.loc[d.index >= pd.Timestamp("2020-02-01", tz="UTC")]
    return d


def horizon_decay(d, feats, hmax=72):
    print("\n===== AUC by forward horizon (1h bars) =====")
    rows = []
    for h in [1, 2, 3, 4, 6, 8, 12, 24, 48, 72]:
        fwd = d["close"].shift(-h) / d["close"] - 1.0
        y = (fwd > 0).astype(int)
        rec = {"h": h}
        for f in feats:
            rec[f] = round(auc(d[f], y)[0], 4)
        rows.append(rec)
    print(pd.DataFrame(rows).to_string(index=False))


def magnitude(d, f, h=1, q=10):
    fwd = (d["close"].shift(-h) / d["close"] - 1.0) * 1e4
    t = pd.DataFrame({"f": d[f], "r": fwd}).dropna()
    t["b"] = pd.qcut(t["f"], q, labels=False, duplicates="drop")
    g = t.groupby("b").agg(n=("r", "size"), f_lo=("f", "min"), f_hi=("f", "max"),
                           bp=("r", "mean"), med=("r", "median"),
                           win=("r", lambda s: (s > 0).mean() * 100))
    g["t"] = g.bp / (t.groupby("b")["r"].std() / np.sqrt(g.n))
    print(f"\n----- {f}: mean forward {h}h return by decile (bp) -----")
    print(g.round(2).to_string())
    sp = g.bp.iloc[-1] - g.bp.iloc[0]
    print(f"top-bottom spread = {sp:.2f} bp  (round-trip taker cost = 8 bp)")


def control(d, f="taker_imb", h=1, nb=5):
    """2-way sort: bucket the past 1h return, then test the flow inside each bucket."""
    r1 = d["close"].pct_change()
    fwd = d["close"].shift(-h) / d["close"] - 1.0
    t = pd.DataFrame({"r1": r1, "f": d[f], "fwd": fwd}).dropna()
    t["rb"] = pd.qcut(t["r1"], nb, labels=False, duplicates="drop")
    print(f"\n----- {f} inside buckets of the just-finished 1h return -----")
    out = []
    for b, grp in t.groupby("rb"):
        a1, n1 = auc(grp["f"], (grp["fwd"] > 0).astype(int))
        a0, _ = auc(grp["f"], (grp["fwd"] <= 0).astype(int))
        # decile spread within the bucket
        gg = grp.copy()
        gg["q"] = pd.qcut(gg["f"], 5, labels=False, duplicates="drop")
        m = gg.groupby("q")["fwd"].mean() * 1e4
        out.append(dict(ret_bucket=b, r1_from=round(grp["r1"].min() * 1e4, 1),
                        r1_to=round(grp["r1"].max() * 1e4, 1), n=len(grp),
                        auc=a1, spread_bp=m.iloc[-1] - m.iloc[0]))
    print(pd.DataFrame(out).round(4).to_string(index=False))

    # residual AUC: demean the flow within each return bucket
    t["f_res"] = t["f"] - t.groupby("rb")["f"].transform("mean")
    a, n = auc(t["f_res"], (t["fwd"] > 0).astype(int))
    print(f"residual-flow AUC (after removing the past-return effect) = {a:.4f}  n={n}")


def orthogonality(d):
    """Does the flow signal know anything the trend strategy does not?"""
    m = pd.read_parquet(D / "daily" / "daily_panel.parquet")
    print("\n----- daily panel cols -----")
    print(list(m.columns)[:20])
    print(m.shape)


def main():
    d = prep()
    d["r1"] = d["close"].pct_change()
    horizon_decay(d, ["taker_imb", "taker_z", "div24", "tlr_cnt_r24", "oi_chg_z"], 72)
    magnitude(d, "taker_imb", 1)
    magnitude(d, "div24", 1)
    magnitude(d, "taker_imb", 24)
    control(d, "taker_imb", 1)
    control(d, "div24", 1)


if __name__ == "__main__":
    main()
