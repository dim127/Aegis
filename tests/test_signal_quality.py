"""Signal-quality tests: cost gating and tick-size precision.

The shapes here are taken verbatim from aegis_signals.db. A signal quoting a
one-cent stop on LINK is not a tradeable signal — round-trip fees would consume
most of 1R — so the scanner must reject it rather than report it.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import db
from tests.dbtemp import use_temp_dbs

import db
import execution
from strategy.aegis_strategy import AegisSMCStrategy

from tests.test_smc_strategy import APPROVED_CONFIG, make_frame, structure_result


class CostGateTests(unittest.TestCase):
    """The min-stop gate rejects setups whose stop is mostly fee."""

    def setUp(self):
        self.strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)
        self.df_htf = make_frame()
        self.df_ltf = make_frame()

    def _run(self, gap_mid: float, sl: float, quantize=None):
        fvg = {
            "index": self.df_ltf.index[-1],
            "displacement_index": self.df_ltf.index[-2],
            "direction": "long",
            "gap_low": gap_mid - 0.01,
            "gap_high": gap_mid + 0.01,
            "gap_mid": gap_mid,
        }
        htf_event = {"direction": "long", "kind": "BOS",
                     "index": self.df_htf.index[-1], "level": 109.0}
        with (
            patch("strategy.aegis_strategy.latest_structure_event",
                  return_value=structure_result(event=htf_event, bullish_bos=True)),
            patch("strategy.aegis_strategy.detect_structure", return_value=structure_result()),
            patch("strategy.aegis_strategy.fair_value_gaps",
                  return_value={"bullish_fvgs": [fvg], "bearish_fvgs": []}),
            patch("strategy.aegis_strategy.order_block_for_event", return_value=None),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([0.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.is_breakout_candle", return_value=False),
            patch("strategy.aegis_strategy.liquidity_inflection", return_value=sl),
            patch("strategy.aegis_strategy.detect_liquidity_sweep", return_value=True),
        ):
            return self.strategy._check_direction(
                self.df_htf, self.df_ltf, "long", quantize=quantize
            )

    def test_default_floor_is_eight_times_round_trip_cost(self):
        self.assertAlmostEqual(self.strategy.round_trip_cost_pct, 0.08)
        self.assertAlmostEqual(self.strategy.min_stop_pct, 0.64)

    def test_link_one_cent_stop_is_rejected(self):
        result = self._run(gap_mid=8.18, sl=8.17)
        self.assertFalse(result["valid"])
        self.assertIn("Stop too tight", result["reason"])

    def test_btc_sub_two_tenths_percent_stop_is_rejected(self):
        # BTC signal id 20: entry 64727.35, sl 64599.73 -> 0.197% stop.
        result = self._run(gap_mid=64727.35, sl=64599.73)
        self.assertFalse(result["valid"])
        self.assertIn("Stop too tight", result["reason"])

    def test_wide_enough_stop_passes_and_reports_net_rr(self):
        result = self._run(gap_mid=100.0, sl=98.0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["rr"], 4.0)
        # Fees shrink the reward and widen the loss, so net RR is below gross.
        self.assertLess(result["rr_net"], result["rr"])
        self.assertGreater(result["rr_net"], 3.0)
        self.assertAlmostEqual(result["risk_pct"], 2.0)

    def test_rejections_still_report_confluence(self):
        result = self._run(gap_mid=8.18, sl=8.17)
        self.assertIn("reasons", result)
        self.assertIn("confluence", result)


class TickQuantizationTests(unittest.TestCase):
    def setUp(self):
        self.strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)

    def test_quantizer_snaps_prices_and_preserves_risk(self):
        gate = CostGateTests("test_link_one_cent_stop_is_rejected")
        gate.setUp()
        # XRP-like tick: 4 decimals. A 2dp round would collapse this risk to 0.01.
        quantize = lambda price: round(price, 4)
        result = gate._run(gap_mid=1.0612, sl=1.0384, quantize=quantize)
        self.assertTrue(result["valid"])
        self.assertEqual(result["entry"], 1.0612)
        self.assertEqual(result["sl"], 1.0384)
        self.assertAlmostEqual(result["risk"], 0.0228, places=6)

    def test_fmt_scales_decimals_with_magnitude(self):
        self.assertEqual(self.strategy._fmt(64727.35), "64727.35")
        self.assertEqual(self.strategy._fmt(81.812), "81.812")
        self.assertEqual(self.strategy._fmt(8.1812), "8.1812")
        self.assertEqual(self.strategy._fmt(1.0612), "1.0612")
        self.assertEqual(self.strategy._fmt(0.06123456), "0.061235")


if __name__ == "__main__":
    unittest.main()


class SignalExpiryTests(unittest.TestCase):
    """A stale PENDING row must not silently mute future signals.

    Expiry used to live in trade_manager.py. When execution was removed, nothing
    retired PENDING rows any more — and because dedup suppresses a repeat while
    one is PENDING, that suppression became permanent: the journal stopped
    recording new signals for any pair/combo/direction it had already seen.
    """

    def setUp(self):
        use_temp_dbs()
        self.setup = {
            "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m", "direction": "long",
            "entry": 100.0, "sl": 95.0, "tp": 115.0, "rr": 3.0,
        }

    def _age_rows(self, hours):
        import sqlite3
        old = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(db._active_paths()[0])
        conn.execute("UPDATE trade_journal SET timestamp = ?", (old,))
        conn.commit()
        conn.close()

    def test_stale_pending_is_expired(self):
        db.log_signal(self.setup)
        self._age_rows(3)
        self.assertEqual(db.expire_stale_signals(15), 1)
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 0)
        self.assertEqual(len(db.fetch_trade_journal("EXPIRED")), 1)

    def test_fresh_pending_survives(self):
        db.log_signal(self.setup)
        self.assertEqual(db.expire_stale_signals(15), 0)
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)

    def test_dedup_suppresses_only_while_the_signal_is_live(self):
        self.assertTrue(db.log_signal(self.setup))
        self.assertFalse(db.log_signal(self.setup), "repeat while live must dedup")
        self._age_rows(3)
        self.assertTrue(db.log_signal(self.setup),
                        "once the old signal expires, a new one must be recorded")
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)

    def test_a_different_direction_is_never_suppressed(self):
        db.log_signal(self.setup)
        self.assertTrue(db.log_signal({**self.setup, "direction": "short"}))
