"""Two structural questions:
1) Does spreading the same signal over a basket of majors (equal risk, total gross capped)
   beat BTC alone once the cap is enforced?
2) How much is the spot-only 100% cap costing us? (leverage sensitivity)
"""
import numpy as np
import pandas as pd

import lab
import opt

C, O, H, L = opt.load_long()
C2 = pd.read_parquet(lab.D / "daily" / "daily_panel.parquet")
C2 = C2[~C2.symbol.isin(["LUNAUSDT", "FTTUSDT"])]
Cc = C2.pivot_table(index="dt", columns="symbol", values="close").sort_index().ffill(limit=3)
Oo = C2.pivot_table(index="dt", columns="symbol", values="open").sort_index().ffill(limit=3)

r = Cc.pct_change()
vol30 = r.rolling(30).std() * np.sqrt(365)
z = lab.zscore(Cc, (20, 40, 60, 90))


def basket(syms, target=0.40, gross_cap=1.0):
    """Equal risk budget per asset; scale down (never up) so gross stays under the cap."""
    W = opt.w_v2(z[syms], vol30[syms], target)
    g = W.abs().sum(axis=1).replace(0, np.nan)
    sc = (gross_cap / g).clip(upper=1.0).fillna(1.0)
    return W.mul(sc, axis=0)


def show(name, W, O, **kw):
    m, eq, ret = opt.run(W, O, **kw)
    print(f"{name:<30} cagr {m['cagr']*100:6.1f}%  sharpe {m['sharpe']:5.2f}  mdd {m['mdd']*100:6.1f}%  "
          f"calmar {m['calmar']:4.2f}  vol {m['vol']*100:4.1f}%  expo {m['expo']*100:5.1f}%")
    return m, ret


print("=== 一篮子主流币（等风险，总仓≤100%，2020-06 起）===")
sets = [["BTCUSDT"], ["BTCUSDT", "ETHUSDT"], ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
        ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
        ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT"]]
rows = []
for s in sets:
    m, ret = show("+".join(x.replace("USDT", "") for x in s), basket(s), Oo, start="2020-06-01")
    m["cfg"] = len(s)
    m["_ret"] = ret
    rows.append(m)
print()
print(pd.DataFrame({r["cfg"]: lab.yearly(r["_ret"]).round(1) for r in rows}).to_string())

print("\n=== 杠杆上限（BTC，2018-2026）===")
c, o = C[["BTCUSDT"]], O[["BTCUSDT"]]
for lev in (1.0, 1.25, 1.5, 2.0):
    w = opt.w_v2(z[["BTCUSDT"]], vol30[["BTCUSDT"]], 0.40, cap=lev)
    show(f"最大 {lev:.2f}x", w, o)

print("\n=== 目标波动率上调（等价于加杠杆）===")
for tv in (0.40, 0.50, 0.60):
    for lev in (1.0, 1.5):
        w = opt.w_v2(z[["BTCUSDT"]], vol30[["BTCUSDT"]], tv, cap=lev)
        show(f"目标{tv:.0%} 上限{lev:.1f}x", w, o)
