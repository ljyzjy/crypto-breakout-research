"""Fixed-rule research baseline. No claim of profitability."""
from pandas import DataFrame
from freqtrade.strategy import IStrategy


class SpotTrendV1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    startup_candle_count = 210
    process_only_new_candles = True
    position_adjustment_enable = False
    minimal_roi = {}
    stoploss = -0.04
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 6},
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": False},
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma50"] = dataframe["close"].rolling(50).mean()
        dataframe["sma200"] = dataframe["close"].rolling(200).mean()
        # Exclude the signal candle from both historical breakout thresholds.
        dataframe["high20"] = dataframe["high"].rolling(20).max().shift(1)
        dataframe["low10"] = dataframe["low"].rolling(10).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        condition = (
            (dataframe["sma50"] > dataframe["sma200"])
            & (dataframe["close"] > dataframe["high20"])
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[condition, ["enter_long", "enter_tag"]] = (1, "trend_breakout")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        condition = (
            ((dataframe["close"] < dataframe["low10"])
             | (dataframe["sma50"] < dataframe["sma200"]))
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[condition, ["exit_long", "exit_tag"]] = (1, "trend_exit")
        return dataframe
