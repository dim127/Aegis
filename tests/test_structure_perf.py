"""PERF-01: speed up structure detection without changing a single signal.

The optimisation reuses one swing computation across the backward search
instead of recomputing it per candidate. That is only safe because of an exact
property: for a slice df[:end], swing_highs marks position i exactly when the
full-frame computation marks it AND i <= end - 1 - window, since the fractal
needs `window` bars on each side and the loop stops `window` short of the edge.

The regression test matters more than the benchmark. An optimisation that
changes which setups fire has not sped anything up — it has silently swapped
the strategy for a different one.
"""
import time
import unittest

import numpy as np
import pandas as pd

from indicators import (
    _swings_for_prefix,
    detect_structure,
    latest_structure_event,
    swing_highs,
    swing_lows,
)


def random_frame(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    spread = np.abs(rng.normal(0, 0.6, n)) + 0.1
    return pd.DataFrame(
        {
            "Open": close + rng.normal(0, 0.2, n),
            "High": close + spread,
            "Low": close - spread,
            "Close": close,
            "Volume": np.abs(rng.normal(100, 20, n)),
        },
        index=pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
    )


class PrefixSwingEquivalenceTests(unittest.TestCase):
    """The property the whole optimisation rests on."""

    def test_prefix_swings_match_recomputation(self):
        for seed in range(8):
            df = random_frame(120, seed)
            full_high = swing_highs(df, 3)
            full_low = swing_lows(df, 3)
            for end in range(30, len(df) + 1, 7):
                sliced = df.iloc[:end]
                expected_high = swing_highs(sliced, 3)
                expected_low = swing_lows(sliced, 3)
                got_high, got_low = _swings_for_prefix(full_high, full_low, end, 3)
                self.assertTrue(
                    got_high.equals(expected_high),
                    f"swing highs diverge at seed={seed} end={end}",
                )
                self.assertTrue(
                    got_low.equals(expected_low),
                    f"swing lows diverge at seed={seed} end={end}",
                )


class StructureOutputUnchangedTests(unittest.TestCase):
    def test_latest_structure_event_identical_to_naive_search(self):
        """Compare against a deliberately naive reimplementation."""
        def naive(df, direction, window=15, max_bars_back=30):
            minimum_length = window + 5
            if len(df) < minimum_length:
                return detect_structure(df, window)
            earliest = max(minimum_length - 1, len(df) - max_bars_back)
            for end in range(len(df), earliest, -1):
                result = detect_structure(df.iloc[:end], window)
                event = result["event"]
                if event is not None and event["direction"] == direction:
                    return result
            return detect_structure(df, window)

        for seed in range(12):
            df = random_frame(140, seed)
            for direction in ("long", "short"):
                fast = latest_structure_event(df, direction, window=15)
                slow = naive(df, direction, window=15)
                self.assertEqual(
                    fast["event"], slow["event"],
                    f"event differs at seed={seed} direction={direction}",
                )
                for key in ("bullish_choch", "bearish_choch", "bullish_bos",
                            "bearish_bos", "bullish_break", "bearish_break"):
                    self.assertEqual(fast[key], slow[key],
                                     f"{key} differs at seed={seed} {direction}")

    def test_detect_structure_accepts_precomputed_swings_without_changing_output(self):
        df = random_frame(140, 99)
        plain = detect_structure(df, window=15)
        seeded = detect_structure(
            df, window=15,
            swings=(swing_highs(df, 3), swing_lows(df, 3)),
        )
        self.assertEqual(plain, seeded)


class BenchmarkTests(unittest.TestCase):
    def test_is_fast_enough_for_a_full_scan(self):
        # 7 pairs x 3 combos x 2 directions = 42 calls per scan; this must stay
        # well inside the 60-second cadence with room for network time.
        df = random_frame(300, 7)
        start = time.perf_counter()
        for _ in range(10):
            latest_structure_event(df, "long", window=15)
        per_call_ms = (time.perf_counter() - start) / 10 * 1000
        self.assertLess(per_call_ms, 25.0,
                        f"{per_call_ms:.1f}ms per call is too slow for 42 calls a scan")


if __name__ == "__main__":
    unittest.main()
