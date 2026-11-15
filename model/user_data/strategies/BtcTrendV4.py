"""BtcTrendV4 -- long/short perpetual trend with a funding gate and a leverage ladder.

What changed versus BtcTrendV3 (spot, long only, max 1x):

1. Shorts are allowed, but only when funding sits in the upper part of its trailing
   one-year distribution. Measured on 2020-2026 perp data, short days inside the gate
   returned +14.9bp/day (win rate 54.5%) and days outside it -11.6bp/day (46.1%).
   Shorting a crowded short is the losing trade, not shorting itself.

2. Leverage is a ladder by default: 1.75x when trend is up, volatility is moderate and
   the book is near its high; 1.25x when conditions are merely acceptable; 1.0x
   otherwise. The ladder does NOT beat a constant multiple at the same average on
   Sharpe (1.20 vs 1.25). It is kept only because it caps exposure in bad regimes.
   Set LEV_FLAT to a number to switch to a constant multiple; see the note there.

3. Nothing above 3x. At 8x the position is liquidated on a 12% adverse day; the one
   such event in the sample turned 37x of equity into zero. 40x survives four months.

4. HOLD THE BASE LONG IN SPOT, not in a perp. A long perp pays funding, and BTC funding
   averaged 11.6%/yr over 2020-2026 and was positive on 88% of days. At the exposure this
   strategy actually carries (32-42%), that is 6.5%/yr of equity handed to the other side
   for nothing. Spot pays none. Only the part above 1x has to be a perp. Measured on the
   same signal, this is worth +9.2pp of CAGR and +0.17 Sharpe, and it cannot decay,
   because it is a settlement rule rather than an estimated effect.
   Operationally: run the base in the spot wallet; if you want leverage above 1x, run a
   second futures instance only for the excess. Do not put the whole position in perps
   because it is convenient.

5. When flat, the capital is idle. It can fund a delta-neutral sleeve (long spot, short
   perp) that collects the same funding instead of paying it: 11.3%/yr on notional, 1.2%
   vol, correlation -0.05 with this book. It is a separate execution, not something this
   class can do, and its yield is decaying (30.7% in 2021, 3.2% in 2026), so size it off
   current funding rather than the seven-year average.

6. Do NOT spread the carry sleeve across the alt universe. A 25-coin book was built and
   tested: after fixing its turnover (55 turns/yr cost 7.7%/yr in fees) it earns
   13.3%/yr on notional at Sharpe 7.3, against 11.2% at Sharpe 8.6 for BTC alone. The
   funding yield on alts is 2pp higher but their basis is 1.5-2x as noisy and the two
   books correlate 0.67. In this portfolio that is +0.8pp of CAGR for 16 legs. Also do
   not try to time the book with breadth, dispersion or funding rank: all six gates
   tested lost to a constant exposure of the same average.

7. Plan on the last 24 months, not the full sample. CAGR 36.8%, vol 32.6%, Sharpe 1.12,
   12m 31.8%/22.1%/1.36 - versus 57%/1.45 for 2020-2026. 2025 returned +12.1% (Sharpe
   0.53); 2026 to October +7.7%. The seven-year figure is carried by 2020-2021.

Execution: signal from the close of day t-1, filled at the open of day t. Freqtrade
does this by default. Funding fees are charged by the engine from the funding_rate data.

8. The position MUST be rebalanced while it is open. Sizing once at entry does not
   reproduce this book: entries fire at z just above 0.20, so the stake is permanently
   small and never grows with the trend. Measured 2020-2026, entry-only sizing returns
   25.3%/yr at Sharpe 1.24 with 0.27x average exposure, against 62.3%/yr at 1.54 with
   0.375x for the daily-rebalanced book. adjust_trade_position() below closes that gap;
   a 0.10 band on drift-per-equity costs 10% less turnover than rebalancing daily and
   tracks just as well (0.20 is too wide: Sharpe 1.475 vs 1.534).

9. Do not improve the denominator. Six ways of estimating volatility were tested against
   each other, including Parkinson, Garman-Klass and hourly realised variance. The best
   forecast is the worst book: EWMA(10) has a QLIKE of 0.323 against 0.379 for the plain
   60-day measure, and produces Sharpe 1.30 against 1.45. Fast estimators cut size right
   after a spike, which is when a trend pays. The 60-day close-to-close window and the
   min(1, .) cap are both at their optimum; so is the z cap of 1.00 (1.50 costs 0.06
   Sharpe, 2.00 costs 0.12). See research/x11-x19.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import IStrategy

log = logging.getLogger(__name__)

FUNDING_CSV = Path(__file__).resolve().parents[1] / "funding_daily.csv"


class BtcTrendV4(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = True
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    position_adjustment_enable = False
    startup_candle_count = 120

    # no hard stop: the exit is the signal flipping. A stop would cut the right tail,
    # which is where this strategy makes all of its money.
    stoploss = -0.99
    trailing_stop = False
    minimal_roi = {"0": 100}

    # ---- rules
    ENTER = 0.20
    TARGET_VOL = 0.40          # notional per unit equity before leverage
    GATE_WINDOW = 365          # trailing days for the funding quantile
    GATE_Q = 0.40
    LEV_HIGH, LEV_MID, LEV_LOW = 1.75, 1.25, 1.0
    LEV_MAX = 3.0              # hard ceiling: liquidation must stay far away
    # Set > 0 to replace the ladder with one constant multiple. The ladder is cosmetic:
    # against a flat book at the same 1.11x average it loses Sharpe (1.22 vs 1.25),
    # because "conviction" does not predict returns (hit rate is 51-53% in every |z|
    # bucket; only the payoff ratio moves, and that is 3 days per bucket). Return scales
    # with the multiple, not with the timing of it -- pick the number from the drawdown
    # you can sit through, not from how sure the signal feels.
    LEV_FLAT = 0.0

    # The book this strategy describes walks to z * min(1, .40/vol) every day: it grows as
    # the trend strengthens and shrinks as volatility rises. Sizing only at entry does not
    # reproduce it -- entries happen at z just above 0.20, so the position is permanently
    # small and never grows into the trend. Measured on 2020-2026, entry-only sizing gives
    # 25.3%/yr at Sharpe 1.24 versus 62.3%/yr at 1.54 for the rebalanced book: the same
    # signal, but only 0.27x average exposure instead of 0.375x, and a worse risk profile.
    # So adjust_trade_position below is not an optimisation, it is what makes the live
    # system the thing that was tested. 0.10 is the widest band that still tracks: at 0.10
    # turnover falls 10% and Calmar improves slightly, at 0.20 the tracking error starts to
    # cost (Sharpe 1.475 vs 1.534).
    REBALANCE_BAND = 0.10      # fraction of equity the target must drift before trading

    _funding: pd.Series | None = None

    # ------------------------------------------------------------------ helpers
    def _funding_series(self) -> pd.Series:
        if BtcTrendV4._funding is None:
            if not FUNDING_CSV.exists():
                log.warning("funding_daily.csv missing; the short gate is disabled")
                BtcTrendV4._funding = pd.Series(dtype=float)
            else:
                f = pd.read_csv(FUNDING_CSV, parse_dates=["date"])
                BtcTrendV4._funding = f.set_index("date")["funding_rate"].sort_index()
        return BtcTrendV4._funding

    # ------------------------------------------------------------------ indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()
        close = df["close"]
        ret = close.pct_change()

        df["vol_ann"] = ret.rolling(60).std() * np.sqrt(365)

        parts = []
        for n in (20, 40, 60, 90):
            v = ret.rolling(n).std() * np.sqrt(n)
            parts.append(((close / close.shift(n) - 1) / v.replace(0, np.nan)).clip(-3, 3))
        df["mom_z"] = sum(parts) / len(parts)

        scale = (self.TARGET_VOL / df["vol_ann"]).clip(upper=1.0)
        df["w_long"] = (df["mom_z"].clip(lower=0, upper=1.0) * scale).where(
            df["mom_z"] > self.ENTER, 0.0).fillna(0.0)
        w_short = ((-df["mom_z"]).clip(lower=0, upper=1.0) * scale).where(
            df["mom_z"] < -self.ENTER, 0.0).fillna(0.0)

        # funding gate: rolling quantile, never full-sample
        f = self._funding_series()
        if len(f):
            key = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
            fr = key.map(f)
            df["funding"] = fr.fillna(0.0).to_numpy()
            thr = (df["funding"].rolling(self.GATE_WINDOW, min_periods=120)
                   .quantile(self.GATE_Q))
            df["gate"] = (df["funding"] > thr).astype(float)
            df.loc[thr.isna(), "gate"] = 1.0
        else:
            df["funding"] = 0.0
            df["gate"] = 1.0
        df["w_short"] = w_short * df["gate"]

        # price-based drawdown proxy (the strategy cannot see account equity here)
        df["dd"] = close / close.rolling(365, min_periods=60).max() - 1.0

        if self.LEV_FLAT > 0:
            df["lev"] = pd.Series(float(self.LEV_FLAT), index=df.index)
        else:
            lev = pd.Series(self.LEV_LOW, index=df.index)
            mid = (df["vol_ann"] < 0.60) & (df["dd"] > -0.20)
            lev = lev.mask(mid, self.LEV_MID)
            high = (df["vol_ann"] < 0.45) & (df["dd"] > -0.10) & (df["mom_z"] > self.ENTER)
            lev = lev.mask(high, self.LEV_HIGH)
            df["lev"] = lev.clip(1.0, self.LEV_MAX).fillna(1.0)

        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[(df["w_long"] > 0) & (df["volume"] > 0), ["enter_long", "enter_tag"]] = (1, "trend_long")
        df.loc[(df["w_short"] > 0) & (df["volume"] > 0), ["enter_short", "enter_tag"]] = (1, "trend_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[df["mom_z"] < 0.0, ["exit_long", "exit_tag"]] = (1, "trend_off")
        df.loc[df["mom_z"] > 0.0, ["exit_short", "exit_tag"]] = (1, "trend_off")
        return df

    # ------------------------------------------------------------------ sizing
    def _last(self, pair: str, when=None) -> pd.Series | None:
        """Last CLOSED candle, never the one being formed.

        The research book takes its weight from the close of day t-1 and fills at the open
        of day t. get_analyzed_dataframe() includes the candle currently being processed,
        whose close is not known yet, so taking iloc[-1] would read the future in backtest
        and flicker in live. Filter on the timestamp instead.
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or len(df) == 0:
            return None
        if when is not None and "date" in df.columns:
            past = df[df["date"] < when]
            if len(past):
                return past.iloc[-1]
        return df.iloc[-1]

    def leverage(self, pair: str, current_time, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        row = self._last(pair, current_time)
        if row is None:
            return self.LEV_LOW
        return float(min(max(row.get("lev", self.LEV_LOW), 1.0), self.LEV_MAX))

    def custom_stake_amount(self, pair: str, current_time, current_rate: float,
                            proposed_stake: float, min_stake: float | None,
                            max_stake: float, leverage: float, entry_tag: str | None,
                            side: str, **kwargs) -> float:
        row = self._last(pair, current_time)
        if row is None:
            return 0.0
        w = float(row["w_long"] if side == "long" else row["w_short"])
        equity = self.wallets.get_total_stake_amount()
        stake = equity * w
        if min_stake and stake < min_stake:
            return 0.0
        return float(min(stake, max_stake))

    def adjust_trade_position(self, trade, current_time, current_rate: float,
                              current_profit: float, min_stake: float | None,
                              max_stake: float, current_entry_rate: float,
                              current_exit_rate: float, current_entry_profit: float,
                              current_exit_profit: float, **kwargs):
        """Walk an open position back toward the target weight.

        This is the part that makes the live book the book that was measured. The target
        is z * min(1, .40/vol) * leverage in notional terms; without this call the stake
        is frozen at its entry size, which is the size implied by z just above 0.20. Over
        2020-2026 that produces 25.3%/yr at Sharpe 1.24 against 62.3%/yr at 1.54.

        Returns (stake_delta, tag), negative to reduce. Bands are on notional drift as a
        fraction of equity, so a 0.10 band tolerates a tenth of the account of tracking
        error before paying 4bp to fix it.
        """
        row = self._last(trade.pair, current_time)
        if row is None:
            return None

        is_short = getattr(trade, "is_short", False)
        w = float(row["w_short"] if is_short else row["w_long"])
        if w <= 0:
            return None                   # going flat is the exit signal's job

        equity = self.wallets.get_total_stake_amount()
        lev = float(getattr(trade, "leverage", 1.0) or 1.0)
        target = equity * w * lev         # notional now, in quote
        current = trade.amount * current_rate
        delta = target - current

        if abs(delta) < self.REBALANCE_BAND * equity:
            return None

        if delta > 0:
            if min_stake and delta < min_stake:
                return None
            return (min(delta, max_stake), "rebalance_up")

        delta = -min(abs(delta), current)  # never cross through zero
        if min_stake and abs(delta) < min_stake:
            return None
        return (delta, "rebalance_down")
