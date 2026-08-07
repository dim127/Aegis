"""Tests for positioning history: source selection and no-lookahead replay.

The backtest previously hardcoded `long_short = None` on the false premise that
no history existed, so every backtested setup scored one confluence factor lower
than the same setup would score live. These tests pin the replay path down.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

import db
import market_metrics as mm


class SourceSelectionTests(unittest.TestCase):
    def test_default_is_position_weighted_top_traders(self):
        key, endpoint = mm._resolve_source(None)
        self.assertEqual(key, "top_position")
        self.assertEqual(endpoint, "topLongShortPositionRatio")

    def test_each_source_maps_to_its_endpoint(self):
        self.assertEqual(mm._resolve_source("global_account")[1], "globalLongShortAccountRatio")
        self.assertEqual(mm._resolve_source("top_account")[1], "topLongShortAccountRatio")

    def test_unknown_source_falls_back_to_default(self):
        key, _ = mm._resolve_source("nonsense")
        self.assertEqual(key, mm.DEFAULT_LONG_SHORT_SOURCE)

    def test_summary_derives_bias_from_the_long_share(self):
        crowd_long = mm._summarise_long_short(
            [{"longAccount": "0.6135", "longShortRatio": "1.5875"}]
        )
        self.assertEqual(crowd_long["long_pct"], 61.4)
        self.assertEqual(crowd_long["short_pct"], 38.6)
        self.assertEqual(crowd_long["bias"], "long")

        crowd_short = mm._summarise_long_short(
            [{"longAccount": "0.3865", "longShortRatio": "0.63"}]
        )
        self.assertEqual(crowd_short["bias"], "short")


class PositioningSeriesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "t.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "s.db")
        self.rows = [
            {"timestamp": 1_000_000, "value": 55.0},
            {"timestamp": 2_000_000, "value": 60.0},
            {"timestamp": 3_000_000, "value": 45.0},
        ]
        db.save_positioning_history("BTC/USDT:USDT", "long_short_top_position", "4h", self.rows)
        self.series = mm.PositioningSeries("BTC/USDT:USDT", "long_short_top_position", "4h")

    def test_series_loads_in_ascending_order(self):
        self.assertEqual(len(self.series), 3)
        self.assertEqual(list(self.series.times), [1_000_000, 2_000_000, 3_000_000])

    def test_exact_timestamp_returns_that_observation(self):
        self.assertEqual(self.series.as_of(2_000_000), 60.0)

    def test_one_ms_early_returns_the_previous_observation(self):
        # The decisive no-lookahead case: a replay must never see a ratio
        # published after the candle it is scoring.
        self.assertEqual(self.series.as_of(1_999_999), 55.0)

    def test_between_observations_returns_the_earlier_one(self):
        self.assertEqual(self.series.as_of(2_500_000), 60.0)

    def test_before_the_series_starts_returns_none(self):
        self.assertIsNone(self.series.as_of(999_999))

    def test_after_the_series_ends_holds_the_last_observation(self):
        self.assertEqual(self.series.as_of(9_000_000), 45.0)

    def test_empty_series_is_safe(self):
        empty = mm.PositioningSeries("NOPE/USDT:USDT", "long_short_top_position", "4h")
        self.assertEqual(len(empty), 0)
        self.assertIsNone(empty.as_of(1_000_000))
        self.assertIsNone(empty.context_as_of(1_000_000))

    def test_context_matches_the_live_payload_shape(self):
        ctx = self.series.context_as_of(2_000_000)
        self.assertEqual(set(ctx), {"long_pct", "short_pct", "ratio", "bias"})
        self.assertEqual(ctx["long_pct"], 60.0)
        self.assertEqual(ctx["short_pct"], 40.0)
        self.assertEqual(ctx["bias"], "long")

    def test_context_flips_bias_below_fifty_percent(self):
        self.assertEqual(self.series.context_as_of(3_000_000)["bias"], "short")

    def test_coverage_reports_span(self):
        cov = db.positioning_coverage("BTC/USDT:USDT", "long_short_top_position", "4h")
        self.assertEqual(cov["rows"], 3)
        self.assertEqual(cov["first"], 1_000_000)
        self.assertEqual(cov["last"], 3_000_000)

    def test_saving_again_is_idempotent(self):
        db.save_positioning_history("BTC/USDT:USDT", "long_short_top_position", "4h", self.rows)
        self.assertEqual(
            db.positioning_coverage("BTC/USDT:USDT", "long_short_top_position", "4h")["rows"], 3
        )


class OpenInterestTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "t.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "s.db")
        hour = 3_600_000
        db.save_positioning_history("BTC/USDT:USDT", "open_interest", "4h", [
            {"timestamp": 10 * hour, "value": 100_000.0},
            {"timestamp": 20 * hour, "value": 110_000.0},
            {"timestamp": 30 * hour, "value": 88_000.0},
        ])
        self.series = mm.PositioningSeries("BTC/USDT:USDT", "open_interest", "4h")
        self.hour = hour

    def test_rising_open_interest_is_positive(self):
        change = self.series.change_pct(20 * self.hour, 10 * self.hour)
        self.assertAlmostEqual(change, 10.0)

    def test_unwinding_open_interest_is_negative(self):
        # A drop means positions were closed out — the footprint of stops being
        # taken rather than new money entering.
        change = self.series.change_pct(30 * self.hour, 10 * self.hour)
        self.assertAlmostEqual(change, -20.0)

    def test_change_is_none_when_lookback_predates_the_series(self):
        self.assertIsNone(self.series.change_pct(10 * self.hour, 10 * self.hour))

    def test_change_never_reads_a_future_observation(self):
        # One ms before the 88k print lands, the latest known value is still
        # 110k, so the change must read +10% and not the -20% it becomes once
        # that observation is published.
        change = self.series.change_pct(30 * self.hour - 1, 10 * self.hour)
        self.assertAlmostEqual(change, 10.0)

    def test_download_persists_sum_open_interest(self):
        payload = [
            {"timestamp": 1_000_000, "sumOpenInterest": "105334.6",
             "sumOpenInterestValue": "6769225047.9"},
        ]

        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return payload

        with patch.object(mm.requests, "get", return_value=R()):
            saved = mm.download_open_interest_history("ETH/USDT:USDT", "4h", 500)
        self.assertEqual(saved, 1)
        series = mm.PositioningSeries("ETH/USDT:USDT", "open_interest", "4h")
        self.assertAlmostEqual(series.as_of(1_000_000), 105334.6)


class FundingZScoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "t.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "s.db")

    def _series(self, values):
        db.save_positioning_history("BTC/USDT:USDT", "funding_rate", "8h", [
            {"timestamp": (i + 1) * 1000, "value": v} for i, v in enumerate(values)
        ])
        return mm.PositioningSeries("BTC/USDT:USDT", "funding_rate", "8h")

    def test_zscore_is_relative_to_the_pairs_own_history(self):
        # Each pair has its own funding baseline, so a fixed threshold measures
        # the pair rather than the signal.
        s = self._series([1.0] * 20 + [5.0])
        z = s.zscore_as_of(21 * 1000)
        self.assertIsNotNone(z)
        self.assertGreater(z, 1.0)

    def test_reading_at_its_own_mean_is_near_zero(self):
        s = self._series([1.0, 2.0] * 10 + [1.5])
        self.assertAlmostEqual(s.zscore_as_of(21 * 1000), 0.0, places=1)

    def test_low_funding_gives_a_negative_zscore(self):
        s = self._series([2.0] * 20 + [-3.0])
        self.assertLess(s.zscore_as_of(21 * 1000), -1.0)

    def test_too_few_observations_returns_none(self):
        s = self._series([1.0, 2.0, 3.0])
        self.assertIsNone(s.zscore_as_of(3 * 1000))

    def test_constant_series_has_no_zscore(self):
        s = self._series([1.0] * 20)
        self.assertIsNone(s.zscore_as_of(20 * 1000))

    def test_zscore_never_reads_a_future_observation(self):
        s = self._series([1.0] * 20 + [9.0])
        before_spike = s.zscore_as_of(21 * 1000 - 1)
        self.assertIsNone(before_spike)  # constant window, spike not yet visible

    def test_download_stores_funding_in_basis_points(self):
        payload = [{"fundingTime": 1_000_000, "fundingRate": "0.00000799"}]

        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return payload

        with patch.object(mm.requests, "get", return_value=R()):
            saved = mm.download_funding_history("BTC/USDT:USDT", 1000)
        self.assertEqual(saved, 1)
        s = mm.PositioningSeries("BTC/USDT:USDT", "funding_rate", "8h")
        self.assertAlmostEqual(s.as_of(1_000_000), 0.0799)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "t.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "s.db")

    def test_download_persists_long_share_as_percent(self):
        payload = [
            {"timestamp": 1_000_000, "longAccount": "0.6135", "longShortRatio": "1.5875"},
            {"timestamp": 2_000_000, "longAccount": "0.4000", "longShortRatio": "0.6667"},
        ]
        with patch.object(mm, "fetch_global_long_short", return_value=payload):
            saved = mm.download_long_short_history("BTC/USDT:USDT", "4h", 500, "top_position")
        self.assertEqual(saved, 2)
        series = mm.PositioningSeries("BTC/USDT:USDT", "long_short_top_position", "4h")
        self.assertAlmostEqual(series.as_of(1_000_000), 61.35)
        self.assertAlmostEqual(series.as_of(2_000_000), 40.0)

    def test_failed_fetch_saves_nothing(self):
        with patch.object(mm, "fetch_global_long_short", return_value=None):
            self.assertEqual(
                mm.download_long_short_history("BTC/USDT:USDT", "4h", 500, "top_position"), 0
            )


if __name__ == "__main__":
    unittest.main()
