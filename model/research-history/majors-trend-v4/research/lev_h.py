"""Does "conviction" predict anything? Measure before levering.

Every candidate confidence axis is bucketed on signal-active days and scored on the
forward *directional* return (sign of the signal x next-day return). Directional, not
account, so the number answers one question: when the model says it is sure, is it
right more often and by more?

If no axis shows a monotone spread, then a conviction tilt is just leverage wearing a
costume, and the leverage-matched control (section D) will expose it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import lev
from lev_a import prep
from lev_d import running_dd
from lev_f import final_rules

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)


# ------------------------------------------------------------------ axes
def kaufman_er(C, n=20):
    """Efficiency ratio: net move / path length. High = clean trend, low = chop."""
    net = (C - C.shift(n)).abs()
    path = C.diff().abs().rolling(n).sum()
    return (net / path.replace(0, np.nan)).clip(0, 1)


def slope_t(C, n=90):
    """t-stat of a rolling linear trend on log price. Trend quality, not magnitude."""
    lp = np.log(C)
    x = np.arange(n) - (n - 1) / 2
    sxx = float((x ** 2).sum())

    def f(w):
        b = float((w * x).sum()) / sxx
        ybar = w.mean()
        syy = float(((w - ybar) ** 2).sum())
        sse = max(syy - b * b * sxx, 1e-18)
        se = np.sqrt(sse / (n - 2) / sxx)
        return b / se if se > 0 else 0.0

    return lp.rolling(n).apply(f, raw=True)


def run_length(active):
    """Consecutive days the signal has been on (same sign), reset on flip."""
    a = active.fillna(0)
    grp = (a.ne(a.shift())).cumsum()
    return a.groupby(grp).cumcount() + 1


def bucket_table(hit, axis, w, labels, name, min_n=60):
    """Quantile buckets by rank, so ties (agree=0.5 etc.) never break qcut."""
    bk = pd.qcut(axis[w].rank(method="first"), len(labels), labels=labels)
    t = pd.DataFrame({"b": bk, "h": hit[w], "a": axis[w]})
    g = t.groupby("b", observed=True).agg(
        n=("h", "size"),
        axis_med=("a", "median"),
        win=("h", lambda s: (s > 0).mean() * 100),
        mean_bp=("h", lambda s: s.mean() * 1e4),
        shp=("h", lambda s: s.mean() / s.std() * np.sqrt(365) if s.std() else np.nan),
    )
    sd = t.groupby("b", observed=True)["h"].std()
    g["t"] = g["mean_bp"] / 1e4 / (sd / np.sqrt(g["n"]))
    g.index.name = name
    return g.round(2)


def main():
    C, O, H, L, F, r, vol, z = prep()
    sym = ["BTCUSDT"]
    args = (C[sym], O[sym], H[sym], L[sym], F[sym])
    kw = dict(start="2020-01-01")
    f = F["BTCUSDT"]
    c = C["BTCUSDT"]

    W, Wl, Ws, gate = final_rules(C[sym], vol[sym], z[sym], f)
    _, _, r1x, _ = lev.simulate(W, 1.0, *args, **kw)
    dd = running_dd(r1x).shift(1).fillna(0.0)

    # ---- forward directional return: signal decided at t-1 close, fills at t open
    Wd = W["BTCUSDT"].shift(1).fillna(0.0)          # weight actually held on day t
    active = Wd.abs() > 1e-9
    dirn = np.sign(Wd)
    hit = dirn * r["BTCUSDT"]                        # directional return on day t
    ok = active & hit.notna()

    print(f"样本 {C.index[0].date()} -> {C.index[-1].date()}  {len(C)} 天")
    print(f"有仓天数 {int(ok.sum())} ({ok.mean()*100:.0f}%)   "
          f"方向日收益均值 {hit[ok].mean()*1e4:+.1f}bp   胜率 {(hit[ok]>0).mean()*100:.1f}%   "
          f"Sharpe {hit[ok].mean()/hit[ok].std()*np.sqrt(365):.2f}")

    # ---- axes, all knowable at the close of t-1
    er = kaufman_er(c, 20)
    st = slope_t(c, 90)
    run = run_length(active)
    agree = sum(np.sign(c / c.shift(n) - 1) for n in (20, 40, 60, 90)) / 4
    vsl = (r["BTCUSDT"].rolling(20).std() / r["BTCUSDT"].rolling(60).std())
    d365 = c / c.rolling(365, min_periods=120).max() - 1
    fq = f.rolling(365, min_periods=120).apply(lambda x: float((x[-1] > x).mean()), raw=True)
    axes = {
        "|z| 信号强度": z["BTCUSDT"].abs(),
        "多周期一致度": agree.abs(),
        "波动率": vol["BTCUSDT"],
        "1x回撤": dd,
        "持仓连续天数": run,
        "趋势效率ER": er,
        "趋势t值": st.abs(),
        "短期/长期波动": vsl,
        "距365日高点": d365,
        "资金费分位": fq,
    }

    print("\n" + "=" * 100)
    print("A. 单维度预测力：把有仓天数按该维度分5桶，看信号方向日收益")
    print("   （若某维度真有信息，均值应单调，Sharpe 也应单调）")
    print("=" * 100)
    lab5 = ["Q1低", "Q2", "Q3", "Q4", "Q5高"]
    for nm, ax in axes.items():
        ax = ax.shift(1)                              # know at t-1 close
        g = bucket_table(hit, ax, ok, lab5, nm)
        mono = "↑" if g["mean_bp"].is_monotonic_increasing else ("↓" if g["mean_bp"].is_monotonic_decreasing else " 乱")
        print(f"\n--- {nm}  (均值单调性 {mono})")
        print(g.to_string())

    # ---- Spearman IC of each axis against the directional hit
    print("\n" + "=" * 100)
    print("B. 秩相关 IC（维度值 vs 方向日收益），附日频 t 值")
    print("=" * 100)
    rows = []
    for nm, ax in axes.items():
        ax = ax.shift(1)
        m = ok & ax.notna() & np.isfinite(ax)
        ic = ax[m].rank().corr(hit[m].rank())
        n = int(m.sum())
        rows.append(dict(维度=nm, IC=ic, t=ic * np.sqrt(n - 2) / np.sqrt(1 - ic ** 2), n=n))
    d = pd.DataFrame(rows).sort_values("t", key=abs, ascending=False)
    print(d.round(3).to_string(index=False))
    print("   |t|>2 才算有点统计意义；10个维度里出现一两个 t=2 是纯噪声的正常水平。")

    # ---- 2-D: signal strength x trend quality, the two most likely survivors
    print("\n" + "=" * 100)
    print("C. 二维交叉：|z| 强度 × 趋势效率 ER（只含有仓日）")
    print("=" * 100)
    zz = z["BTCUSDT"].abs().shift(1)
    ee = er.shift(1)
    zq = pd.qcut(zz[ok], 3, labels=["z弱", "z中", "z强"], duplicates="drop")
    eq = pd.qcut(ee[ok], 3, labels=["ER低", "ER中", "ER高"], duplicates="drop")
    t = pd.DataFrame({"z": zq, "e": eq, "h": hit[ok]})
    piv = t.pivot_table(index="z", columns="e", values="h",
                        aggfunc=lambda s: s.mean() / s.std() * np.sqrt(365) if s.std() else np.nan)
    cnt = t.pivot_table(index="z", columns="e", values="h", aggfunc="size")
    print("\nSharpe（行=|z|，列=ER）:")
    print(piv.round(2).to_string())
    print("\n天数:")
    print(cnt.to_string())
    piv2 = t.pivot_table(index="z", columns="e", values="h", aggfunc=lambda s: (s > 0).mean() * 100)
    print("\n胜率%:")
    print(piv2.round(1).to_string())

    # ---- save the frame for the next stage
    frame = pd.DataFrame({
        "W": W["BTCUSDT"], "hit": hit, "ok": ok, "z_abs": zz, "er": ee,
        "vol": vol["BTCUSDT"].shift(1), "dd": dd, "run": run.shift(1),
        "agree": agree.abs().shift(1), "st": st.abs().shift(1),
        "vsl": vsl.shift(1), "d365": d365.shift(1), "fq": fq.shift(1),
    })
    frame.to_parquet(lev.D.parent / "out" / "conv_frame.parquet")
    print("\n已保存 out/conv_frame.parquet")


if __name__ == "__main__":
    main()
