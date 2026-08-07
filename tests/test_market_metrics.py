import unittest
from contextlib import ExitStack
from unittest.mock import patch

import pandas as pd

from market_metrics import (
    estimate_liquidation_clusters,
    long_short_24h,
    symbol_to_binance,
)
from strategy.aegis_strategy import AegisSMCStrategy


class BinanceSymbolTests(unittest.TestCase):
    def test_unified_pair_maps_to_binance_symbol(self):
        self.assertEqual(symbol_to_binance("BTC/USDT:USDT"), "BTCUSDT")
        self.assertEqual(symbol_to_binance("SOL/USDT:USDT"), "SOLUSDT")


class LongShortRatioTests(unittest.TestCase):
    def test_parses_and_averages_24h_samples(self):
        rows = [
            {"symbol": "BTCUSDT", "longAccount": "0.6", "longShortRatio": "1.5", "shortAccount": "0.4"},
            {"symbol": "BTCUSDT", "longAccount": "0.6", "longShortRatio": "1.5", "shortAccount": "0.4"},
        ]
        with patch("market_metrics.db.get_market_metric", return_value=None), \
             patch("market_metrics.fetch_global_long_short", return_value=rows), \
             patch("market_metrics.db.set_market_metric"):
            result = long_short_24h("BTC/USDT:USDT")
        self.assertEqual(result["long_pct"], 60.0)
        self.assertEqual(result["short_pct"], 40.0)
        self.assertEqual(result["bias"], "long")

    def test_returns_none_when_fetch_fails(self):
        with patch("market_metrics.db.get_market_metric", return_value=None), \
             patch("market_metrics.fetch_global_long_short", return_value=None):
            result = long_short_24h("BTC/USDT:USDT")
        self.assertIsNone(result)


def make_bumpy_df(rows=200):
    index = pd.date_range("2026-01-01", periods=rows, freq="min", tz="UTC")
    closes = [100.0 + (i % 61) * 0.5 - 15.0 for i in range(rows)]
    lows = [c - 0.5 for c in closes]
    highs = [c + 0.5 for c in closes]
    vols = [1000.0 * (1 + (i % 7)) for i in range(rows)]
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows,
         "Close": closes, "Volume": vols},
        index=index,
    )


class LiquidationClusterTests(unittest.TestCase):
    def test_estimate_returns_above_and_below(self):
        df = make_bumpy_df()
        result = estimate_liquidation_clusters(df)
        self.assertIsNotNone(result)
        self.assertIn("nearest_above", result)
        self.assertIn("nearest_below", result)

    def test_estimate_is_deterministic(self):
        df = make_bumpy_df()
        first = estimate_liquidation_clusters(df)
        second = estimate_liquidation_clusters(df)
        self.assertEqual(first, second)

    def test_estimate_returns_none_for_short_frame(self):
        self.assertIsNone(estimate_liquidation_clusters(make_bumpy_df(10)))


class StrategyMarketFactorTests(unittest.TestCase):
    def setUp(self):
        config = {
            "smc_pairs": ["BTC", "ETH", "BNB", "SOL", "HYPE"],
            "smc": {"rr_target": 3.0, "atr_proximity": 2.0, "min_confluence": 3},
        }
        self.strategy = AegisSMCStrategy(exchange=object(), config=config)
        self.df_15m = make_bumpy_df()
        self.df_1m = make_bumpy_df()
        self.fvg = {
            "index": self.df_1m.index[-1], "displacement_index": self.df_1m.index[-2],
            "direction": "long", "gap_low": 100.0, "gap_high": 105.0, "gap_mid": 102.5,
        }

    def _enter(self, market_ctx):
        event = {"direction": "long", "kind": "BOS",
                 "index": self.df_15m.index[-1], "level": 109.0}
        ob = {"index": self.df_15m.index[-2], "high": 105.0, "low": 100.0,
              "fully_mitigated": False, "mitigation_ratio": 0.0}
        stack = ExitStack()
        stack.enter_context(patch("strategy.aegis_strategy.latest_structure_event",
                                  return_value=self._structure_result(event, bos=True)))
        stack.enter_context(patch("strategy.aegis_strategy.detect_structure",
                                  return_value=self._structure_result(None, bos=False)))
        stack.enter_context(patch("strategy.aegis_strategy.fair_value_gaps",
                                  return_value={"bullish_fvgs": [self.fvg], "bearish_fvgs": []}))
        stack.enter_context(patch("strategy.aegis_strategy.order_block_for_event", return_value=ob))
        stack.enter_context(patch("strategy.aegis_strategy.atr",
                                  return_value=pd.Series([1.0] * 10)))
        stack.enter_context(patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False))
        stack.enter_context(patch("strategy.aegis_strategy.is_breakout_candle", return_value=False))
        stack.enter_context(patch("strategy.aegis_strategy.liquidity_inflection", return_value=95.0))
        stack.enter_context(patch("strategy.aegis_strategy.detect_liquidity_sweep", return_value=True))
        return stack

    @staticmethod
    def _structure_result(event, bos):
        return {
            "bullish_choch": False, "bearish_choch": False,
            "bullish_bos": bos, "bearish_bos": False,
            "last_swing_high": 109.0, "last_swing_low": 90.0, "event": event,
        }

    def test_contrarian_long_short_factor_counts_when_crowd_is_short(self):
        market_ctx = {
            "long_short": {"long_pct": 40.0, "short_pct": 60.0, "ratio": 0.67, "bias": "short"},
            "clusters": None,
        }
        with self._enter(market_ctx):
            result = self.strategy._check_direction(
                self.df_15m, self.df_1m, "long", market_ctx=market_ctx)

        self.assertTrue(result["valid"])
        self.assertTrue(any("Long/Short" in r and "supports long" in r for r in result["reasons"]))

    def test_crowd_aligned_direction_has_no_long_short_factor(self):
        market_ctx = {
            "long_short": {"long_pct": 60.0, "short_pct": 40.0, "ratio": 1.5, "bias": "long"},
            "clusters": None,
        }
        with self._enter(market_ctx):
            result = self.strategy._check_direction(
                self.df_15m, self.df_1m, "long", market_ctx=market_ctx)

        self.assertTrue(result["valid"])
        self.assertFalse(any("Long/Short" in r for r in result["reasons"]))

    def test_cluster_factor_counts_within_proximity(self):
        market_ctx = {
            "long_short": None,
            "clusters": {"nearest_above": None,
                         "nearest_below": {"price": 101.5, "density": 1.0, "strength": "strong"}},
        }
        with self._enter(market_ctx):
            result = self.strategy._check_direction(
                self.df_15m, self.df_1m, "long", market_ctx=market_ctx)

        self.assertTrue(result["valid"])
        self.assertTrue(any("Liquidation cluster" in r for r in result["reasons"]))


if __name__ == "__main__":
    unittest.main()