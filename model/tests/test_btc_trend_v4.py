"""Regression checks for sizing, funding and closed-candle handling."""
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd


STRATEGY = Path(__file__).resolve().parents[1] / "user_data/strategies/BtcTrendV4.py"
spec = importlib.util.spec_from_file_location("btc_trend_v4_under_test", STRATEGY)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StrategyChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_funding = module.FUNDING_CSV
        self.addCleanup(setattr, module, "FUNDING_CSV", self.old_funding)
        module.FUNDING_CSV = Path(self.temp.name) / "funding.csv"
        module.BtcTrendV4._funding = None
        module.BtcTrendV4._funding_signature = None
        self.strategy = module.BtcTrendV4({})
        self.strategy.wallets = SimpleNamespace(get_total_stake_amount=lambda: 1000.0)
        self.dates = pd.date_range("2025-01-01", periods=400, freq="1D", tz="UTC")
        t = np.arange(len(self.dates))
        self.frame = pd.DataFrame({"date": self.dates, "close": 100 + 0.1*t + np.sin(t/4), "volume": 1.0})

    def write_funding(self, last=0.002, duplicate=False):
        values = pd.DataFrame({"date": self.dates.strftime("%Y-%m-%d"), "funding_rate": 0.001})
        values.loc[values.index[-1], "funding_rate"] = last
        if duplicate:
            values = pd.concat([values, values.tail(1)], ignore_index=True)
        values.to_csv(module.FUNDING_CSV, index=False)
        stat = module.FUNDING_CSV.stat()
        os.utime(module.FUNDING_CSV, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

    def test_funding_missing_is_unknown_and_blocks_new_short(self):
        result = self.strategy.populate_indicators(self.frame, {})
        self.assertTrue(result["funding"].isna().all())
        self.assertTrue((result["gate"] == 0).all())
        self.assertTrue((result["w_short"] == 0).all())

    def test_funding_changes_are_reloaded_and_duplicates_fail_closed(self):
        self.write_funding(last=0.002)
        first = self.strategy.populate_indicators(self.frame, {})
        self.assertEqual(first["gate"].iloc[-1], 1.0)
        self.assertTrue((first["gate"].iloc[:119] == 0).all())
        self.write_funding(last=-0.002)
        second = self.strategy.populate_indicators(self.frame, {})
        self.assertEqual(second["gate"].iloc[-1], 0.0)
        self.write_funding(last=0.002, duplicate=True)
        third = self.strategy.populate_indicators(self.frame, {})
        self.assertTrue(pd.isna(third["funding"].iloc[-1]))
        self.assertEqual(third["gate"].iloc[-1], 0.0)

    def test_adjustment_uses_stake_units_and_current_tier(self):
        trade = SimpleNamespace(pair="BTC/USDT:USDT", is_short=False, leverage=2.0,
                                amount=5.0, stake_amount=250.0, has_open_orders=False)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.strategy._last = lambda *args: {"w_long": 0.6, "lev": 1.5}
        args = (trade, now, 100.0, 0.0, 1.0, 1000.0, 100.0, 100.0, 0.0, 0.0)
        self.assertEqual(self.strategy.adjust_trade_position(*args), (200.0, "rebalance_up"))
        self.strategy._last = lambda *args: {"w_long": 0.5, "lev": 1.5}
        args = (trade, now, 200.0, 0.0, 1.0, 1000.0, 200.0, 200.0, 0.0, 0.0)
        stake, tag = self.strategy.adjust_trade_position(*args)
        self.assertEqual(tag, "rebalance_down")
        self.assertAlmostEqual(stake, -62.5)
        self.assertAlmostEqual(-stake * trade.amount / trade.stake_amount, 1.25)
        trade.has_open_orders = True
        self.assertIsNone(self.strategy.adjust_trade_position(*args))

    def test_no_future_candle_and_exchange_leverage_limit(self):
        candle = pd.DataFrame({"date": self.dates[:2], "lev": [1.75, 1.75]})
        self.strategy.dp = SimpleNamespace(get_analyzed_dataframe=lambda *args: (candle, None))
        self.assertIsNone(self.strategy._last("BTC/USDT:USDT", self.dates[0]))
        self.assertEqual(self.strategy._last("BTC/USDT:USDT", self.dates[1])["date"], self.dates[0])
        actual = self.strategy.leverage("BTC/USDT:USDT", self.dates[1], 100.0, 1.0, 1.2, None, "long")
        self.assertEqual(actual, 1.2)

    def test_exit_zero_is_optional(self):
        frame = pd.DataFrame({"mom_z": [0.1], "w_long": [0.0], "w_short": [0.0]})
        self.assertFalse(self.strategy.EXIT_WHEN_TARGET_ZERO)
        original = self.strategy.populate_exit_trend(frame.copy(), {})
        self.assertTrue(pd.isna(original["exit_long"].iloc[0]))
        self.strategy.EXIT_WHEN_TARGET_ZERO = True
        alternate = self.strategy.populate_exit_trend(frame.copy(), {})
        self.assertEqual(alternate["exit_long"].iloc[0], 1.0)


if __name__ == "__main__":
    unittest.main()
