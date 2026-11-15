"""BtcTrendV2 — risk-budgeted time-series momentum on BTC, spot only.

Signal: z = mean over 20/40/60/90d of (momentum / its own vol), clipped to +/-3.
Target weight = clip(z, 0, 1) * min(1, TARGET_VOL / realised 30d vol).
Rebalanced daily at the next open; partial rebalances only when the gap exceeds
REBALANCE_BAND of equity, which keeps turnover near 13x/year.

Exit is a full close when the target weight reaches zero (z <= 0).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class BtcTrendV2(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False
    startup_candle_count = 130
    process_only_new_candles = True

    TARGET_VOL = 0.40          # annualised risk budget for the strategy
    LOOKBACKS = (20, 40, 60, 90)
    Z_CAP = 1.0                # momentum above this adds no extra size
    REBALANCE_BAND = 0.05      # rebalance only if |target - held| > 5% of equity
    MIN_WEIGHT = 0.05          # do not bother opening below this

    minimal_roi = {"0": 1000}
    stoploss = -0.99           # exits are signal driven; no hard stop
    trailing_stop = False
    use_custom_stoploss = False
    position_adjustment_enable = True
    max_entry_position_adjustment = -1

    # ------------------------------------------------------------------ signals
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        r = dataframe["close"].pct_change()
        parts = []
        for L in self.LOOKBACKS:
            v = r.rolling(L).std() * np.sqrt(L)
            parts.append(((dataframe["close"] / dataframe["close"].shift(L) - 1) / v.replace(0, np.nan)).clip(-3, 3))
        dataframe["z"] = sum(parts) / len(parts)
        dataframe["vol_ann"] = r.rolling(30).std() * np.sqrt(365)
        scale = (self.TARGET_VOL / dataframe["vol_ann"]).clip(upper=1.0)
        dataframe["target_w"] = (dataframe["z"].clip(lower=0, upper=self.Z_CAP) * scale).fillna(0.0)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["target_w"] > self.MIN_WEIGHT, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["target_w"] <= 0.0, "exit_long"] = 1
        return dataframe

    # ------------------------------------------------------------------ sizing
    def _target(self, pair: str, when) -> float:
        """Target weight decided at the close *before* `when`.

        In backtesting the analysed dataframe holds the whole history, so slicing by
        timestamp is mandatory — using .iloc[-1] would read the future and never trade.
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or len(df) == 0:
            return 0.0
        past = df[df["date"] < when]
        if len(past) == 0:
            return 0.0
        return float(past["target_w"].iloc[-1])

    def custom_stake_amount(self, pair: str, current_time, current_rate: float, proposed_stake: float,
                            min_stake: float | None, max_stake: float, leverage: float,
                            entry_tag: str | None, side: str, **kwargs) -> float | None:
        w = self._target(pair, current_time)
        equity = self.wallets.get_total_stake_amount()
        stake = min(equity * w, max_stake)
        if min_stake and stake < min_stake:
            return None
        return stake

    def adjust_trade_position(self, trade, current_time, current_rate: float, current_profit: float,
                             min_stake: float | None, max_stake: float, current_entry_rate: float,
                             current_exit_rate: float, current_entry_profit: float,
                             current_exit_profit: float, **kwargs):
        w = self._target(trade.pair, current_time)
        if w <= 0.0:
            return None                      # let the exit signal close it
        equity = self.wallets.get_total_stake_amount()
        if equity <= 0:
            return None
        held = trade.amount * current_rate
        delta = w * equity - held
        if abs(delta) < self.REBALANCE_BAND * equity:
            return None
        if delta > 0:
            delta = min(delta, max_stake)
            return (delta, "rebalance_up") if delta > 0 else None
        return (delta, "rebalance_down")
