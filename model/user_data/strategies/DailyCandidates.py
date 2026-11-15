"""Pre-specified spot adaptations of established rule families; not paper replicas."""
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import IStrategy


class DailyCommon(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    startup_candle_count = 1800
    process_only_new_candles = True
    position_adjustment_enable = False
    minimal_roi = {}
    stoploss = -0.04
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    family = "ma"
    fast = 20
    slow = 60
    entry_window = 55
    exit_window = 20
    momentum_window = 30
    band_window = 20

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 6},
            {"method": "StoplossGuard", "lookback_period_candles": 48,
             "trade_limit": 2, "stop_duration_candles": 24, "only_per_pair": False},
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frame = dataframe.copy()
        indexed = frame.set_index("date")
        daily = indexed.resample("1D", closed="left", label="right").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        counts = indexed["close"].resample("1D", closed="left", label="right").count()
        daily = daily.loc[counts == 24].copy()
        # The daily row becomes available only when its final hourly candle closes.
        # A full future day in a batch cannot merge into earlier hourly candles.
        close = daily["close"]
        daily["daily_fast"] = close.rolling(self.fast).mean()
        daily["daily_slow"] = close.rolling(self.slow).mean()
        daily["daily_upper_channel"] = daily.high.rolling(self.entry_window).max().shift(1)
        daily["daily_lower_channel"] = daily.low.rolling(self.exit_window).min().shift(1)
        daily["daily_momentum"] = close / close.shift(self.momentum_window) - 1
        daily["daily_mid"] = close.rolling(self.band_window).mean()
        daily["daily_lower_band"] = daily.daily_mid - 2 * close.rolling(self.band_window).std(ddof=0)
        if self.family == "donchian":
            buy = close > daily.daily_upper_channel
            sell = close < daily.daily_lower_channel
        elif self.family == "ma":
            buy = daily.daily_fast > daily.daily_slow
            sell = daily.daily_fast < daily.daily_slow
        elif self.family == "momentum":
            buy = daily.daily_momentum > 0
            sell = daily.daily_momentum <= 0
        elif self.family == "bollinger":
            buy = ((close.shift(1) < daily.daily_lower_band.shift(1))
                   & (close > daily.daily_lower_band) & (close < daily.daily_mid))
            sell = close >= daily.daily_mid
        else:
            raise ValueError(self.family)
        daily["daily_buy"] = buy.astype(int)
        daily["daily_sell"] = sell.astype(int)
        available = daily[[c for c in daily if c.startswith("daily_")]].reset_index()
        available = available.rename(columns={"date": "available_at"})
        frame["available_at"] = frame["date"] + pd.Timedelta(hours=1)
        # Archive Feather uses millisecond timestamps; resampling/arithmetic may
        # yield a different resolution. merge_asof requires identical dtypes.
        frame["available_at"] = frame["available_at"].dt.as_unit("ns")
        available["available_at"] = available["available_at"].dt.as_unit("ns")
        frame = pd.merge_asof(frame.sort_values("available_at"), available,
                              on="available_at", direction="backward")
        frame.index = dataframe.index
        return frame.drop(columns="available_at")

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        valid = ((dataframe.date.dt.hour == 23) & (dataframe.daily_buy == 1)
                 & (dataframe.volume > 0))
        dataframe.loc[valid, ["enter_long", "enter_tag"]] = (1, self.family)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        valid = ((dataframe.date.dt.hour == 23) & (dataframe.daily_sell == 1)
                 & (dataframe.volume > 0))
        dataframe.loc[valid, ["exit_long", "exit_tag"]] = (1, self.family)
        return dataframe


class DailyDonchian(DailyCommon):
    family = "donchian"


class DailyMA(DailyCommon):
    family = "ma"


class DailyMomentum(DailyCommon):
    family = "momentum"


class DailyBollinger(DailyCommon):
    family = "bollinger"


class DonchianLow(DailyDonchian):
    entry_window = 44
    exit_window = 16


class DonchianHigh(DailyDonchian):
    entry_window = 66
    exit_window = 24


class MALow(DailyMA):
    fast = 16
    slow = 48


class MAHigh(DailyMA):
    fast = 24
    slow = 72


class MomentumLow(DailyMomentum):
    momentum_window = 24


class MomentumHigh(DailyMomentum):
    momentum_window = 36


class BollingerLow(DailyBollinger):
    band_window = 16


class BollingerHigh(DailyBollinger):
    band_window = 24
