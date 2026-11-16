"""Temporal-invariance check on synthetic data; not a profit backtest."""
from pathlib import Path

import numpy as np
import pandas as pd
from freqtrade.resolvers import StrategyResolver
from freqtrade.configuration import Configuration

ROOT = Path(__file__).resolve().parent


def main():
    config = Configuration({"config": [str(ROOT / "config.paper.json"),
                                       str(ROOT / "config.public-data.json")],
                            "user_data_dir": str(ROOT / "user_data")}).get_config()
    strategy = StrategyResolver.load_strategy(config)
    rng = np.random.default_rng(7301)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.012, 900)))
    frame = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=900, freq="h", tz="UTC"),
                          "open": close, "high": close * 1.004, "low": close * 0.996,
                          "close": close, "volume": np.ones(900) * 100})

    def analyze(data):
        data = strategy.populate_indicators(data.copy(), {})
        data = strategy.populate_entry_trend(data, {})
        return strategy.populate_exit_trend(data, {})

    full = analyze(frame)
    columns = ["sma50", "sma200", "high20", "low10", "enter_long", "exit_long"]
    for boundary in [250, 450, 650, 850]:
        pd.testing.assert_frame_equal(full.loc[:boundary - 1, columns],
                                      analyze(frame.iloc[:boundary])[columns])
    mutated = frame.copy()
    mutated.loc[600:, ["open", "high", "low", "close"]] *= 10
    pd.testing.assert_frame_equal(full.loc[:599, columns], analyze(mutated).loc[:599, columns])
    assert not ((full.enter_long == 1) & (full.exit_long == 1)).any()
    assert full.enter_long.iloc[:199].sum() == 0
    assert full.enter_long.sum() > 0 and full.exit_long.sum() > 0
    print("PASS: Freqtrade strategy load, prefix invariance, future mutation, warmup, no colliding signals")
    print("Synthetic checks only; profitability and actual fills are not established.")


if __name__ == "__main__":
    main()
