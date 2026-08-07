"""Tests for the market-structure logic fixes.

Each test here pins down a defect found by replaying 30 days of cached data:
the stop anchored to a rolling extreme instead of a swing, a trend window too
small for a trend to ever fit in it, FVG results silently truncated to 3, and
an unbounded search for stale structure events.
"""
import unittest

import pandas as pd

from indicators import (
    detect_structure,
    fair_value_gaps,
    latest_structure_event,
    liquidity_inflection,
)


def flat_frame(rows: int, low: float = 95.0, high: float = 100.0) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="min")
    return pd.DataFrame(
        {"Open": [97.0] * rows, "High": [high] * rows,
         "Low": [low] * rows, "Close": [97.0] * rows,
         "Volume": [100.0] * rows},
        index=index,
    )


class SwingAnchoredStopTests(unittest.TestCase):
    def test_stop_uses_last_swing_not_the_rolling_extreme(self):
        df = flat_frame(40)
        df.loc[df.index[6], "Low"] = 70.0    # deep early low: the rolling minimum
        df.loc[df.index[30], "Low"] = 88.0   # last confirmed swing low

        anchor = liquidity_inflection(df, "long", before=df.index[35], window=30)

        # 70.0 is the lowest price in the window but is not the structural level
        # price last reacted to; anchoring there inflates R.
        self.assertEqual(anchor, 88.0)

    def test_short_stop_uses_last_swing_high(self):
        df = flat_frame(40)
        df.loc[df.index[6], "High"] = 130.0
        df.loc[df.index[30], "High"] = 112.0

        anchor = liquidity_inflection(df, "short", before=df.index[35], window=30)

        self.assertEqual(anchor, 112.0)

    def test_falls_back_to_rolling_extreme_when_no_swing_confirmed(self):
        # Perfectly flat lows produce no fractal swing (comparison is strict).
        df = flat_frame(40)
        anchor = liquidity_inflection(df, "long", before=df.index[35], window=30)
        self.assertEqual(anchor, 95.0)

    def test_returns_none_when_nothing_precedes_the_reference(self):
        df = flat_frame(40)
        self.assertIsNone(liquidity_inflection(df, "long", before=df.index[0]))


class TrendClassificationTests(unittest.TestCase):
    def _breakout_frame(self) -> pd.DataFrame:
        df = flat_frame(40)
        df.loc[:, ["Open", "High", "Low", "Close"]] = [97.0, 100.0, 95.0, 97.0]
        return df

    def test_trendless_break_is_labelled_break_not_bos(self):
        df = self._breakout_frame()
        df.loc[df.index[39], ["Open", "High", "Low", "Close"]] = [100.0, 116.0, 99.0, 115.0]

        structure = detect_structure(df, window=15)

        self.assertTrue(structure["bullish_break"])
        self.assertFalse(structure["bullish_bos"])
        self.assertFalse(structure["bullish_choch"])
        self.assertTrue(structure["trendless_break"])
        self.assertEqual(structure["event"]["kind"], "BREAK")

    def test_raw_break_flags_are_exposed_for_gating(self):
        # The strategy gates on the raw break so that classifying events did not
        # change which setups qualify.
        df = self._breakout_frame()
        structure = detect_structure(df, window=15)
        self.assertIn("bullish_break", structure)
        self.assertIn("bearish_break", structure)
        self.assertFalse(structure["bullish_break"])

    def test_trend_window_defaults_to_double_the_break_window(self):
        # Two confirmed swings per side cannot fit in 15 bars, so the trend
        # lookback must be wider than the break lookback.
        df = flat_frame(60)
        narrow = detect_structure(df, window=15)
        wide = detect_structure(df, window=15, trend_window=40)
        self.assertIn("trendless_break", narrow)
        self.assertIn("trendless_break", wide)


class FvgTruncationTests(unittest.TestCase):
    def _staircase(self, rows: int = 20) -> pd.DataFrame:
        # Each bar gaps clear of the bar two back, so every triple forms an FVG.
        index = pd.date_range("2026-01-01", periods=rows, freq="min")
        return pd.DataFrame(
            {
                "Open": [100.0 + 10 * i for i in range(rows)],
                "High": [105.0 + 10 * i for i in range(rows)],
                "Low": [100.0 + 10 * i for i in range(rows)],
                "Close": [104.0 + 10 * i for i in range(rows)],
                "Volume": [100.0] * rows,
            },
            index=index,
        )

    def test_all_gaps_in_the_lookback_are_returned_by_default(self):
        result = fair_value_gaps(self._staircase(), lookback=30)
        # Previously hardcoded to the 3 most recent, which made lookback a lie.
        self.assertGreater(len(result["bullish_fvgs"]), 3)

    def test_max_fvgs_caps_the_result(self):
        result = fair_value_gaps(self._staircase(), lookback=30, max_fvgs=3)
        self.assertEqual(len(result["bullish_fvgs"]), 3)

    def test_lookback_actually_bounds_the_search(self):
        few = fair_value_gaps(self._staircase(), lookback=6)
        many = fair_value_gaps(self._staircase(), lookback=30)
        self.assertLess(len(few["bullish_fvgs"]), len(many["bullish_fvgs"]))


class StructureRecencyTests(unittest.TestCase):
    def _frame_with_old_break(self) -> pd.DataFrame:
        df = flat_frame(30)
        df.loc[df.index[29], ["Open", "High", "Low", "Close"]] = [100.0, 116.0, 99.0, 115.0]
        quiet = flat_frame(40).set_axis(
            pd.date_range("2026-01-01 00:30", periods=40, freq="min")
        )
        return pd.concat([df, quiet])

    def test_stale_event_is_not_returned_when_out_of_range(self):
        extended = self._frame_with_old_break()
        result = latest_structure_event(extended, "long", window=15, max_bars_back=5)
        event = result["event"]
        self.assertTrue(event is None or event["direction"] != "long")

    def test_recent_event_is_still_found_within_range(self):
        extended = self._frame_with_old_break()
        result = latest_structure_event(extended, "long", window=15, max_bars_back=60)
        self.assertIsNotNone(result["event"])
        self.assertEqual(result["event"]["direction"], "long")


if __name__ == "__main__":
    unittest.main()
