"""MajorsTrendV1 - daily ensemble time-series momentum on BTC/ETH, long only.

Rules are fixed before looking at any backtest of this file:
  z_L = (close/close[L] - 1) / (stdev(1d return, L) * sqrt(L))   for L in 20/40/60/90
  z   = mean(z_L), clipped to [-3, 3]
  enter long when z > 0.30
  exit long when z < 0
  execution at next daily open (freqtrade default), 50% of wallet per slot, 2 slots.
No stoploss tuning, no ROI table: the exit is the signal itself.
"""
from __future__ import annotations

import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class MajorsTrendV1(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False
    startup_candle_count = 220
    process_only_new_candles = True
    position_adjustment_enable = False
    minimal_roi = {}
    stoploss = -0.35
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    LOOKBACKS = (20, 40, 60, 90)
    ENTER_Z = 0.30
    EXIT_Z = 0.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ret = dataframe["close"].pct_change()
        zs = []
        for L in self.LOOKBACKS:
            mom = dataframe["close"] / dataframe["close"].shift(L) - 1
            sigma = ret.rolling(L).std() * np.sqrt(L)
            z = (mom / sigma.replace(0, np.nan)).clip(-3, 3)
            dataframe[f"z{L}"] = z
            zs.append(z)
        dataframe["z"] = sum(zs) / len(zs)
        dataframe["trend_ok"] = (dataframe["z"] > self.ENTER_Z).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        cond = (dataframe["trend_ok"] == 1) & (dataframe["volume"] > 0)
        dataframe.loc[cond, ["enter_long", "enter_tag"]] = (1, "tsmom_ensemble")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        cond = (dataframe["z"] < self.EXIT_Z) & (dataframe["volume"] > 0)
        dataframe.loc[cond, ["exit_long", "exit_tag"]] = (1, "tsmom_off")
        return dataframe
