"""Idle-capital sleeves: does anything earn while the trend signal is flat?

Tested as a standalone edge first (does the signal have any information at all),
then combined with the trend book.
"""
import numpy as np
import pandas as pd

import lab
import opt

C, O, H, L = opt.load_long()
c = C["BTCUSDT"]
r = c.pct_change()
vol30 = r.rolling(30).std() * np.sqrt(365)
z = lab.zscore(C, (20, 40, 60, 90))

ma200 = c.rolling(200).mean()
ma100 = c.rolling(100).mean()
rv5 = c / c.shift(5) - 1
rv3 = c / c.shift(3) - 1
rv10 = c / c.shift(10) - 1


def sleeve(sig, hold, exit_gain=None):
    """sig: bool Series (decided at close t). Enter at close t (filled at open t+1 by run()).
    Hold `hold` days, or exit early when the trade gains `exit_gain`."""
    s = sig.fillna(False).to_numpy()
    p = c.to_numpy()
    n = len(s)
    w = np.zeros(n)
    left = 0
    entry_px = np.nan
    for t in range(n - 1):
        if left > 0:
            left -= 1
            if exit_gain is not None and p[t] / entry_px - 1 >= exit_gain:
                left = 0
        if left == 0 and s[t]:
            left = hold
            entry_px = p[t]
        w[t] = 1.0 if left > 0 else 0.0
    return pd.Series(w, index=c.index)


def show(name, W, O):
    m, eq, ret = opt.run(W, O)
    print(f"{name:<34} cagr {m['cagr']*100:6.1f}%  sharpe {m['sharpe']:5.2f}  mdd {m['mdd']*100:6.1f}%  "
          f"expo {m['expo']*100:5.1f}%  turn {m['turn']:5.1f}  worstY {m['worst_y']*100:6.1f}%")
    return m, ret


print("=== 单笔逆势买跌（独立检验，满仓持有）===")
for thr in (-0.06, -0.08, -0.10):
    for hold in (3, 5, 10):
        s = (rv5 < thr) & (c > ma200)
        W = sleeve(s, hold).to_frame("BTCUSDT") * 1.0
        show(f"牛市 5日跌{thr:.0%} 持{hold}天", W, O)

print("\n=== 不加牛市过滤 ===")
for thr in (-0.08, -0.10):
    s = rv5 < thr
    show(f"5日跌{thr:.0%} 持5天", sleeve(s, 5).to_frame("BTCUSDT"), O)

print("\n=== 顺势回调（趋势中买跌）===")
for thr in (-0.05, -0.08):
    s = (rv5 < thr) & (z["BTCUSDT"] > 0.5)
    show(f"z>0.5 且5日跌{thr:.0%} 持5天", sleeve(s, 5).to_frame("BTCUSDT"), O)
