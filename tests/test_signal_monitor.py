"""Signal lifecycle: published -> triggered -> resolved, from price alone.

This is how Aegis learns whether its own signals worked without placing an
order. The ordering rules below are the whole point, so they are pinned:

  * a stop reached before entry is INVALIDATED, not a loss — the entry never
    happened, and recording it as a loss would corrupt the win rate with
    trades that were never taken
  * a stop reached after entry is a real loss and must be recorded as -1R
"""
import unittest
from unittest.mock import patch

import pandas as pd

import db
import signal_monitor
from tests.dbtemp import use_temp_dbs


def pending(direction="long", **over):
    base = {
        "id": 1, "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m",
        "direction": direction, "status": "PENDING",
        "entry": 100.0, "sl": 95.0, "tp": 115.0,
        "timestamp": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S"),
    }
    base.update(over)
    return base


class PendingTransitionTests(unittest.TestCase):
    def test_price_reaching_entry_triggers(self):
        self.assertEqual(signal_monitor.evaluate(pending(), 100.0)[0], "TRIGGERED")

    def test_price_above_entry_leaves_a_long_waiting(self):
        self.assertIsNone(signal_monitor.evaluate(pending(), 104.0))

    def test_stop_before_entry_invalidates_rather_than_losing(self):
        # The decisive rule. Entry never happened, so this is not a loss and
        # must not be counted as one.
        status, reason = signal_monitor.evaluate(pending(), 94.0)
        self.assertEqual(status, "INVALIDATED")
        self.assertIn("sebelum entry", reason)

    def test_short_triggers_when_price_rises_to_entry(self):
        s = pending("short", entry=100.0, sl=105.0, tp=85.0)
        self.assertEqual(signal_monitor.evaluate(s, 100.0)[0], "TRIGGERED")

    def test_short_invalidates_when_price_runs_past_the_stop(self):
        s = pending("short", entry=100.0, sl=105.0, tp=85.0)
        self.assertEqual(signal_monitor.evaluate(s, 106.0)[0], "INVALIDATED")

    def test_stale_pending_expires(self):
        old = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        status, _ = signal_monitor.evaluate(pending(timestamp=old), 104.0, ttl_minutes=15)
        self.assertEqual(status, "EXPIRED")

    def test_a_triggered_setup_is_never_expired_by_age(self):
        old = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        s = pending(status="TRIGGERED", timestamp=old)
        self.assertIsNone(signal_monitor.evaluate(s, 104.0, ttl_minutes=15))


class TriggeredResolutionTests(unittest.TestCase):
    def test_target_closes_as_tp(self):
        s = pending(status="TRIGGERED")
        self.assertEqual(signal_monitor.evaluate(s, 115.0), ("CLOSED", "TP"))

    def test_stop_after_entry_is_a_real_loss(self):
        s = pending(status="TRIGGERED")
        self.assertEqual(signal_monitor.evaluate(s, 95.0), ("CLOSED", "SL"))

    def test_stop_is_checked_before_target(self):
        # A bar that spans both must not be scored as a win.
        s = pending(status="TRIGGERED")
        self.assertEqual(signal_monitor.evaluate(s, 94.0)[1], "SL")

    def test_mid_move_stays_open(self):
        self.assertIsNone(signal_monitor.evaluate(pending(status="TRIGGERED"), 107.0))


class ProgressTests(unittest.TestCase):
    def test_progress_is_measured_in_r_from_entry(self):
        self.assertAlmostEqual(signal_monitor.progress_r(pending(), 105.0), 1.0)

    def test_progress_is_negative_against_the_position(self):
        self.assertAlmostEqual(signal_monitor.progress_r(pending(), 97.5), -0.5)

    def test_progress_prefers_the_recorded_fill(self):
        s = pending(fill_price=101.0)
        # risk becomes |101-95| = 6, so +6 of move is exactly 1R.
        self.assertAlmostEqual(signal_monitor.progress_r(s, 107.0), 1.0)

    def test_zero_risk_yields_no_progress(self):
        self.assertIsNone(signal_monitor.progress_r(pending(sl=100.0), 105.0))


class CheckAllTests(unittest.TestCase):
    def setUp(self):
        use_temp_dbs()
        db.log_signal({
            "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m", "direction": "long",
            "entry": 100.0, "sl": 95.0, "tp": 115.0, "rr": 3.0,
        })

    def test_waiting_signal_is_reported_valid(self):
        with patch.object(signal_monitor.execution, "fetch_price", return_value=104.0):
            report = signal_monitor.check_all()
        self.assertEqual(len(report["valid"]), 1)
        self.assertEqual(report["valid"][0]["status"], "PENDING")

    def test_touching_entry_records_a_fill_and_stays_valid(self):
        with patch.object(signal_monitor.execution, "fetch_price", return_value=100.0):
            report = signal_monitor.check_all()
        self.assertEqual(report["valid"][0]["status"], "TRIGGERED")
        self.assertEqual(len(db.fetch_trade_journal("TRIGGERED")), 1)
        self.assertEqual(db.fetch_trade_journal("TRIGGERED")[0]["fill_price"], 100.0)

    def test_a_full_round_trip_records_realised_r(self):
        with patch.object(signal_monitor.execution, "fetch_price", return_value=100.0):
            signal_monitor.check_all()
        with patch.object(signal_monitor.execution, "fetch_price", return_value=115.0):
            report = signal_monitor.check_all()
        self.assertEqual(report["invalid"][0]["reason"], "TP")
        closed = db.fetch_trade_journal("CLOSED")[0]
        self.assertAlmostEqual(closed["realized_r"], 3.0)

    def test_unavailable_price_leaves_the_signal_untouched(self):
        with patch.object(signal_monitor.execution, "fetch_price", return_value=None):
            report = signal_monitor.check_all()
        self.assertEqual(report["valid"], [])
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)

    def test_price_is_fetched_once_per_pair(self):
        db.log_signal({
            "pair": "BTC/USDT:USDT", "tf_combo": "1h/5m", "direction": "short",
            "entry": 110.0, "sl": 115.0, "tp": 95.0, "rr": 3.0,
        })
        with patch.object(signal_monitor.execution, "fetch_price",
                          return_value=104.0) as fetch:
            signal_monitor.check_all()
        self.assertEqual(fetch.call_count, 1, "same pair must not be fetched twice")


if __name__ == "__main__":
    unittest.main()
