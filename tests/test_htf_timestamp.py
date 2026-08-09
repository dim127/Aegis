"""BUG-03b: an HTF structure event confirms at candle close, not open.

The index carried on a structure event is the candle's *open* timestamp, and
that value was compared directly against LTF timestamps to decide which FVGs
formed "after" the break. An LTF gap forming inside the HTF candle — before the
break was confirmed — therefore passed as post-structure.

The review this came from described comparing raw array indices across
timeframes. That cannot happen here: Aegis carries pandas timestamps, so index
42 on 15m is never confused with index 42 on 1h. The timestamp semantics were
the real hole.
"""
import unittest

import pandas as pd

from strategy.aegis_strategy import AegisSMCStrategy


class HtfConfirmationTimeTests(unittest.TestCase):
    def setUp(self):
        self.strategy = AegisSMCStrategy(exchange=object())

    def test_htf_event_confirms_at_close_not_open(self):
        # A 4h candle opening at 08:00 is only confirmed at 12:00.
        opened = pd.Timestamp("2026-01-01 08:00", tz="UTC")
        confirmed = self.strategy._event_confirmed_at({"index": opened}, "4h")
        self.assertEqual(confirmed, pd.Timestamp("2026-01-01 12:00", tz="UTC"))

    def test_ltf_event_confirms_at_its_own_close(self):
        opened = pd.Timestamp("2026-01-01 08:00", tz="UTC")
        confirmed = self.strategy._event_confirmed_at({"index": opened}, "15m")
        self.assertEqual(confirmed, pd.Timestamp("2026-01-01 08:15", tz="UTC"))

    def test_gap_inside_the_htf_candle_is_not_post_structure(self):
        # The decisive case: a 15m gap at 09:00 sits inside the 08:00-12:00 4h
        # candle, so at 09:00 the break had not been confirmed yet.
        opened = pd.Timestamp("2026-01-01 08:00", tz="UTC")
        confirmed = self.strategy._event_confirmed_at({"index": opened}, "4h")
        gap_time = pd.Timestamp("2026-01-01 09:00", tz="UTC")
        self.assertLess(gap_time, confirmed,
                        "a gap inside the HTF candle must count as pre-structure")

    def test_gap_after_the_htf_candle_closes_is_post_structure(self):
        opened = pd.Timestamp("2026-01-01 08:00", tz="UTC")
        confirmed = self.strategy._event_confirmed_at({"index": opened}, "4h")
        gap_time = pd.Timestamp("2026-01-01 12:15", tz="UTC")
        self.assertGreaterEqual(gap_time, confirmed)

    def test_unknown_timeframe_falls_back_to_the_raw_index(self):
        opened = pd.Timestamp("2026-01-01 08:00", tz="UTC")
        self.assertEqual(
            self.strategy._event_confirmed_at({"index": opened}, "nonsense"), opened
        )

    def test_missing_event_returns_none(self):
        self.assertIsNone(self.strategy._event_confirmed_at(None, "4h"))


if __name__ == "__main__":
    unittest.main()
