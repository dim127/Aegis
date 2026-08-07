"""Risk-layer tests: position sizing, cost gating, and position lifecycle.

The signal shapes here are taken verbatim from aegis_signals.db, where a
1-cent-quantized stop on LINK produced a $8,180 notional order against $1,000
of stated capital.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import db
import execution
import trade_manager
from strategy.aegis_strategy import AegisSMCStrategy

from tests.test_smc_strategy import APPROVED_CONFIG, make_frame, structure_result


class PositionSizingTests(unittest.TestCase):
    def test_risk_is_one_percent_of_capital(self):
        size = execution.calculate_position_size(1000.0, 1.0, 100.0, 95.0)
        self.assertAlmostEqual(size, 2.0)
        self.assertAlmostEqual(size * (100.0 - 95.0), 10.0)

    def test_sizing_is_independent_of_leverage(self):
        # Leverage changes the margin posted, not the loss at the stop. The old
        # formula multiplied size by it, so leverage 3 risked 3% not 1%.
        self.assertEqual(
            execution.calculate_position_size(1000.0, 1.0, 100.0, 95.0),
            execution.calculate_position_size(1000.0, 1.0, 100.0, 95.0, 300.0),
        )

    def test_zero_stop_distance_returns_zero(self):
        self.assertEqual(execution.calculate_position_size(1000.0, 1.0, 100.0, 100.0), 0.0)

    def test_notional_cap_blocks_the_link_blowup(self):
        # LINK signal id 19: entry 8.18, sl 8.17 -> risk $0.01 -> 1000 LINK.
        uncapped = 10.0 / 0.01
        size = execution.calculate_position_size(1000.0, 1.0, 8.18, 8.17, 300.0)
        self.assertLess(size, uncapped)
        self.assertLessEqual(size * 8.18, 3000.0 + 1e-6)

    def test_non_positive_capital_returns_zero(self):
        self.assertEqual(execution.calculate_position_size(0.0, 1.0, 100.0, 95.0), 0.0)


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


class MonitorPlacedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "t.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "s.db")
        db.log_signal({
            "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m", "direction": "long",
            "entry": 100.0, "sl": 95.0, "tp": 115.0, "rr": 3.0,
        })
        db.update_trade_status(1, "PLACED", "order-1")
        self.trade = db.fetch_trade_journal("PLACED")[0]

    def test_epoch_millisecond_timestamp_does_not_raise(self):
        # ccxt returns order['timestamp'] as an int; subtracting it from a
        # datetime used to raise TypeError and abort the whole monitor pass.
        recent_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        order = {"status": "open", "timestamp": recent_ms}
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.fetch_order", return_value=order),
            patch("trade_manager.execution.cancel_order") as cancel,
        ):
            trade_manager.monitor_placed(self.trade, 60)
        cancel.assert_not_called()
        self.assertEqual(db.fetch_trade_journal("PLACED")[0]["status"], "PLACED")

    def test_order_older_than_fill_window_is_cancelled(self):
        stale_ms = int((pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=3)).timestamp() * 1000)
        order = {"status": "open", "timestamp": stale_ms}
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.fetch_order", return_value=order),
            patch("trade_manager.execution.cancel_order") as cancel,
        ):
            trade_manager.monitor_placed(self.trade, 60)
        cancel.assert_called_once_with("order-1", "BTC/USDT:USDT")
        self.assertEqual(len(db.fetch_trade_journal("CANCELLED")), 1)

    def test_fill_records_price_and_attaches_stops(self):
        order = {"status": "closed", "timestamp": 1, "average": 99.8, "filled": 2.0}
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.fetch_order", return_value=order),
            patch("trade_manager.execution.place_stop_orders",
                  return_value=({"id": "sl-1"}, {"id": "tp-1"})) as stops,
        ):
            trade_manager.monitor_placed(self.trade, 60)
        stops.assert_called_once()
        opened = db.fetch_trade_journal("OPEN")[0]
        self.assertEqual(opened["fill_price"], 99.8)
        self.assertEqual(opened["sl_order_id"], "sl-1")
        self.assertEqual(opened["tp_order_id"], "tp-1")

    def test_placed_without_order_id_is_cancelled_not_requeued(self):
        db.update_trade_status(1, "PLACED", "")
        trade = db.fetch_trade_journal("PLACED")[0]
        with patch("trade_manager.execution.has_credentials", return_value=True):
            trade_manager.monitor_placed(trade, 60)
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 0)
        self.assertEqual(len(db.fetch_trade_journal("CANCELLED")), 1)


class MonitorOpenTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "t.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "s.db")
        db.log_signal({
            "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m", "direction": "long",
            "entry": 100.0, "sl": 95.0, "tp": 115.0, "rr": 3.0,
        })
        db.update_trade_status(1, "OPEN", "order-1")
        db.record_fill(1, 100.0)
        db.record_stop_orders(1, "sl-1", "tp-1")
        self.trade = db.fetch_trade_journal("OPEN")[0]

    def test_position_fetch_failure_does_not_close_the_trade(self):
        # fetch_positions returns None on error. Treating that as "flat" would
        # orphan a live position and free the pair for a stacked entry.
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.fetch_positions", return_value=None),
        ):
            trade_manager.monitor_open(self.trade)
        self.assertEqual(len(db.fetch_trade_journal("OPEN")), 1)
        self.assertEqual(len(db.fetch_trade_journal("CLOSED")), 0)

    def test_zero_contract_position_counts_as_flat(self):
        flat = [{"symbol": "BTC/USDT:USDT", "side": "long", "contracts": 0}]
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.fetch_positions", return_value=flat),
            patch("trade_manager.execution.fetch_price", return_value=115.0),
            patch("trade_manager.execution.cancel_order"),
        ):
            trade_manager.monitor_open(self.trade)
        self.assertEqual(len(db.fetch_trade_journal("CLOSED")), 1)

    def test_live_position_stays_open(self):
        live = [{"symbol": "BTC/USDT:USDT", "side": "long", "contracts": 2.0}]
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.fetch_positions", return_value=live),
        ):
            trade_manager.monitor_open(self.trade)
        self.assertEqual(len(db.fetch_trade_journal("OPEN")), 1)

    def test_close_cancels_the_surviving_stop_and_records_r(self):
        flat = []
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.fetch_positions", return_value=flat),
            patch("trade_manager.execution.fetch_price", return_value=115.0),
            patch("trade_manager.execution.cancel_order") as cancel,
        ):
            trade_manager.monitor_open(self.trade)
        self.assertEqual(cancel.call_count, 2)  # both SL and TP ids cancelled
        closed = db.fetch_trade_journal("CLOSED")[0]
        self.assertEqual(closed["status"], "CLOSED")
        summary = db.performance_summary()
        self.assertEqual(summary["trades"], 1)
        self.assertAlmostEqual(summary["expectancy_r"], 3.0)

    def test_realized_r_is_measured_against_the_actual_fill(self):
        db.record_fill(1, 101.0)  # 1.0 of entry slippage
        trade = db.fetch_trade_journal("OPEN")[0]
        realized = db.record_exit(trade["id"], 115.0, "TP")
        # risk = |101 - 95| = 6, pnl = 14 -> 2.33R, not the nominal 3R.
        self.assertAlmostEqual(realized, 14.0 / 6.0)


class StaleSignalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "t.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "s.db")

    def test_signal_older_than_ttl_is_expired_not_placed(self):
        db.log_signal({
            "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m", "direction": "long",
            "entry": 100.0, "sl": 95.0, "tp": 115.0, "rr": 3.0,
        })
        old = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=13)).strftime("%Y-%m-%d %H:%M:%S")
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute("UPDATE trade_journal SET timestamp = ? WHERE id = 1", (old,))
        conn.commit()
        conn.close()

        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.place_limit_order") as place,
            patch("trade_manager.execution.fetch_equity", return_value=1000.0),
        ):
            trade_manager.run_once()

        place.assert_not_called()
        self.assertEqual(len(db.fetch_trade_journal("EXPIRED")), 1)

    def test_fresh_signal_survives_the_ttl_check(self):
        db.log_signal({
            "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m", "direction": "long",
            "entry": 100.0, "sl": 95.0, "tp": 115.0, "rr": 3.0,
        })
        self.assertEqual(trade_manager.expire_stale_signals(15), 0)
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)


if __name__ == "__main__":
    unittest.main()
