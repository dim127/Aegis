import os
import tempfile
import unittest
from unittest.mock import patch

import db
from tests.dbtemp import use_temp_dbs
import trade_manager


class OnePositionPerPairTests(unittest.TestCase):
    def setUp(self):
        use_temp_dbs()
        self._order = {"id": "o1"}

    def _journal(self, pair, direction="long", entry=100.0):
        db.log_signal({
            "pair": pair,
            "tf_combo": "15m/1m",
            "direction": direction,
            "entry": entry,
            "sl": 95.0 if direction == "long" else 105.0,
            "tp": 115.0 if direction == "long" else 85.0,
            "rr": 3.0,
        })

    def _place_once(self):
        with (
            patch("trade_manager.execution.has_credentials", return_value=True),
            patch("trade_manager.execution.place_limit_order", return_value=self._order),
            patch("trade_manager.execution.place_stop_orders", return_value=(None, None)),
            patch("trade_manager.execution.fetch_order", return_value=None),
            patch("trade_manager.execution.fetch_equity", return_value=1000.0),
            patch("trade_manager.execution.quantize_amount", side_effect=lambda s, a: a),
            patch("trade_manager.execution.meets_exchange_minimums", return_value=True),
        ):
            trade_manager.run_once()

    def test_second_signal_on_same_pair_is_deduped_before_journal(self):
        # Entry is an FVG midpoint that drifts every scan, so dedup keys on the
        # setup identity, not the price — the second never reaches the journal.
        self._journal("BTC/USDT:USDT")
        self._journal("BTC/USDT:USDT", entry=98.0)
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)
        self._assert_after_setup(placed=1, pending=0)

    def test_second_signal_on_different_pair_is_placed(self):
        self._journal("BTC/USDT:USDT")
        self._journal("ETH/USDT:USDT")
        self._assert_after_setup(placed=2, pending=0)

    def test_short_on_same_pair_still_journals(self):
        self._journal("BTC/USDT:USDT", direction="long")
        self._journal("BTC/USDT:USDT", direction="short")
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 2)

    def test_pending_is_skipped_while_trade_placed_on_pair(self):
        self._journal("BTC/USDT:USDT")
        self._place_once()
        self.assertEqual(len(db.fetch_trade_journal("PLACED")), 1)
        self._journal("BTC/USDT:USDT", entry=97.0)
        self._place_once()
        placed = db.fetch_trade_journal("PLACED")
        self.assertEqual(len(placed), 1)
        self.assertIsNotNone(db.fetch_trade_journal("PENDING"))

    def test_concurrent_position_cap_is_enforced(self):
        for pair in ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "LINK/USDT:USDT"):
            self._journal(pair)
        with patch.object(trade_manager, "load_risk_config",
                          return_value={**trade_manager.DEFAULT_RISK,
                                        "max_concurrent_positions": 2}):
            self._place_once()
        self.assertEqual(len(db.fetch_trade_journal("PLACED")), 2)
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), 2)

    def _assert_after_setup(self, placed: int, pending: int):
        self._place_once()
        self.assertEqual(len(db.fetch_trade_journal("PLACED")), placed)
        self.assertEqual(len(db.fetch_trade_journal("PENDING")), pending)


if __name__ == "__main__":
    unittest.main()