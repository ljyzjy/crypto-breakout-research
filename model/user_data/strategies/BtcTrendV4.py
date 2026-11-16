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
   0.375x for the daily-rebalanced book. adjust_trade_position() implements a 0.10 drift
   band; execution, wallet accounting and exit differences mean it still needs a separate
   Freqtrade backtest before it can be compared with the research book.

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
    # Must be True: freqtrade only calls adjust_trade_position() when this flag is on.
    # With False the stake stays frozen at its entry size (the 25.3%/yr book, note 8).
    position_adjustment_enable = True
    # The drawdown proxy and the funding quantile both look back 365 days. A backtest that
    # starts mid-history only gets this many candles of warm-up, so 120 left both windows
    # half-formed for the first eight months of any sub-period run.
    startup_candle_count = 365

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
    # adjust_trade_position enables sizing changes, subject to exchange minimums, available
    # margin, the wallet's accounting and the chosen exit rule. It does not guarantee that
    # Freqtrade reproduces the daily-rebalanced research engine.
    REBALANCE_BAND = 0.10      # fraction of equity the target must drift before trading

    # OPEN QUESTION, left at the shipped behaviour (False). This file closes a position
    # when mom_z crosses 0. The research book (research/x10.py, lev.signal_weight) is flat
    # as soon as the target weight is 0: when |z| falls to 0.20, and for a short also when
    # the funding gate shuts. In between, this file keeps the last size it had. True makes
    # the exit match the research book. It changes when trades close, so it is a decision
    # about the strategy, not a bug fix; measure both before choosing.
    EXIT_WHEN_TARGET_ZERO = False

    _funding: pd.Series | None = None
    _funding_signature: tuple[str, int, int] | None = None

    # ------------------------------------------------------------------ helpers
    def _funding_series(self) -> pd.Series:
        """Daily funding from the CSV, re-read whenever the file changes on disk.

        The file used to be read once per process, so a bot left running never saw the
        days appended after it started.
        """
        try:
            stat = FUNDING_CSV.stat()
            signature = (str(FUNDING_CSV), stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        if BtcTrendV4._funding is None or signature != BtcTrendV4._funding_signature:
            if signature is None:
                log.warning("funding_daily.csv missing; new shorts are blocked")
                BtcTrendV4._funding = pd.Series(dtype=float)
            else:
                try:
                    f = pd.read_csv(FUNDING_CSV)
                    dates = pd.to_datetime(f["date"], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize()
                    rates = pd.to_numeric(f["funding_rate"], errors="coerce")
                    valid = dates.notna() & rates.notna() & np.isfinite(rates)
                    duplicate = dates.duplicated(keep=False) & dates.notna()
                    if duplicate.any():
                        log.warning("Duplicate funding dates are unknown and will block new shorts")
                    BtcTrendV4._funding = pd.Series(
                        rates[valid & ~duplicate].to_numpy(dtype=float),
                        index=dates[valid & ~duplicate], dtype=float,
                    ).sort_index()
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    log.warning("Cannot read funding_daily.csv; new shorts are blocked: %s", exc)
                    BtcTrendV4._funding = pd.Series(dtype=float)
                    signature = None  # retry on the next call
            BtcTrendV4._funding_signature = signature
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
            # A day that is not in the CSV is unknown, not zero. Writing 0.0 let a stale
            # file decide the gate (0 > threshold) and left fake zeros in the quantile
            # window. Unknown funding keeps the gate shut for that day and says so.
            df["funding"] = fr.to_numpy(dtype=float)
            thr = (df["funding"].rolling(self.GATE_WINDOW, min_periods=120)
                   .quantile(self.GATE_Q))
            df["gate"] = (df["funding"] > thr).astype(float)
            if len(df) and pd.isna(df["funding"].iloc[-1]):
                log.warning("funding_daily.csv has no value for %s; shorts stay blocked "
                            "until the file is updated", key.iloc[-1].date())
        else:
            df["funding"] = np.nan
            df["gate"] = 0.0
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
        if self.EXIT_WHEN_TARGET_ZERO:
            df.loc[df["w_long"] <= 0.0, ["exit_long", "exit_tag"]] = (1, "target_zero")
            df.loc[df["w_short"] <= 0.0, ["exit_short", "exit_tag"]] = (1, "target_zero")
            return df
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
        if when is not None:
            if "date" not in df.columns:
                return None
            past = df[df["date"] < when]
            return past.iloc[-1] if len(past) else None
        return df.iloc[-1]

    def leverage(self, pair: str, current_time, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        row = self._last(pair, current_time)
        if row is None:
            return float(min(self.LEV_LOW, max_leverage))
        return float(min(max(row.get("lev", self.LEV_LOW), 1.0), self.LEV_MAX, max_leverage))

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

        The target is z * min(1, .40/vol) * the current leverage tier in notional terms.
        Freqtrade's available stake balance is used as the sizing base; this may differ
        from the research engine's marked-to-market account equity.

        Returns (stake_delta, tag), negative to reduce. Bands are on notional drift as a
        fraction of equity, so a 0.10 band tolerates a tenth of the account of tracking
        error before paying 4bp to fix it.

        Units. The drift is measured in notional, but freqtrade wants the answer as
        stake (margin before leverage):
          - an increase of stake S buys S * trade.leverage of notional;
          - a decrease of stake S sells the fraction S / trade.stake_amount of the
            position, whatever the price has done since entry.
        Returning the notional itself over-trades by the leverage on the way up, and by
        leverage * current_rate / open_rate on the way down.

        Ladder. Freqtrade fixes a trade's leverage at entry, so the tier in force today
        is applied through the size of the target instead. The margin mode and the
        liquidation distance stay those of the entry tier.
        """
        if getattr(trade, "has_open_orders", False):
            return None
        row = self._last(trade.pair, current_time)
        if row is None:
            return None

        is_short = getattr(trade, "is_short", False)
        w = float(row["w_short"] if is_short else row["w_long"])
        if w <= 0:
            return None                   # going flat is the exit signal's job

        equity = self.wallets.get_total_stake_amount()
        trade_lev = float(getattr(trade, "leverage", 1.0) or 1.0)
        tier = row.get("lev", trade_lev)
        tier = trade_lev if pd.isna(tier) else float(min(max(tier, 1.0), self.LEV_MAX))

        target = equity * w * tier        # notional now, in quote
        current = trade.amount * current_rate
        delta = target - current          # notional

        if current <= 0 or abs(delta) < self.REBALANCE_BAND * equity:
            return None

        if delta > 0:
            stake = min(delta / trade_lev, max_stake)
            if stake <= 0 or (min_stake and stake < min_stake):
                return None
            return (stake, "rebalance_up")

        fraction = min(abs(delta) / current, 1.0)   # never cross through zero
        stake = fraction * float(trade.stake_amount)
        if min_stake and stake < min_stake:
            return None
        return (-stake, "rebalance_down")
