import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))
from DailyCandidates import (DailyDonchian, DailyMA, DailyMomentum, DailyBollinger,
    DonchianLow, DonchianHigh, MALow, MAHigh, MomentumLow, MomentumHigh,
    BollingerLow, BollingerHigh)

classes = [DailyDonchian, DailyMA, DailyMomentum, DailyBollinger, DonchianLow,
           DonchianHigh, MALow, MAHigh, MomentumLow, MomentumHigh, BollingerLow, BollingerHigh]
rng = np.random.default_rng(4813)
close = 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.013, 6000)))
data = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=6000, freq="h", tz="UTC"),
                     "open": close, "high": close * 1.004, "low": close * .996,
                     "close": close, "volume": 100.})
for cls in classes:
    strategy = cls({})
    def calc(frame):
        result = strategy.populate_indicators(frame.copy(), {})
        result = strategy.populate_entry_trend(result, {})
        return strategy.populate_exit_trend(result, {})
    result = calc(data)
    milliseconds = data.copy()
    milliseconds["date"] = milliseconds["date"].dt.as_unit("ms")
    pd.testing.assert_frame_equal(result.drop(columns="date"), calc(milliseconds).drop(columns="date"))
    cols = [c for c in result if c.startswith("daily_")] + ["enter_long", "exit_long"]
    for cutoff in [1801, 1823, 1824, 1825, 2500, 4991, 4992]:
        pd.testing.assert_frame_equal(result.iloc[:cutoff][cols], calc(data.iloc[:cutoff])[cols])
    changed = data.copy()
    changed.loc[4000:, ["open", "high", "low", "close"]] *= 10
    pd.testing.assert_frame_equal(result.iloc[:4000][cols], calc(changed).iloc[:4000][cols])
    assert not ((result.enter_long == 1) & (result.exit_long == 1)).any()
    assert ((result.enter_long == 0) | (result.date.dt.hour == 23)).all()
    assert ((result.exit_long == 0) | (result.date.dt.hour == 23)).all()
    # A 23-hour incomplete day cannot affect same-day daily features.
    assert result.iloc[:23][[c for c in result if c.startswith('daily_')]].isna().all().all()
    print(f"PASS {cls.__name__}: temporal invariance / partial-day exclusion / signals", flush=True)
