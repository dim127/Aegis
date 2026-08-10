"""MFE/MAE must be measured over the trade, not past its exit.

extend_win_paths deliberately walks a winner's path forward beyond its
exit so the RR sweep can re-classify a 3R win as a loss at 4R. That is correct
for the sweep and wrong for excursion metrics: mfe_r and mae_r were computed
from the same extended path, so they counted bars from after the position was
already closed.

The symptom was a contradiction that cannot happen in a correct simulation —
winners reporting a median MAE of -1.07R, i.e. having traded through their own
stop and still being recorded as wins.

Every number derived from these fields was affected, which is why this is
verified against a hand-checked trade rather than trusted.
"""
import unittest

import pandas as pd

from analysis.backtest.simulate import Position, extend_win_paths


def ltf_frame(bars):
    index = pd.date_range("2026-01-01", periods=len(bars), freq="1min", tz="UTC")
    return pd.DataFrame(
        [{"Open": h, "High": h, "Low": l, "Close": l, "Volume": 1.0} for h, l in bars],
        index=index,
    )


def make_position(**over):
    sig = {
        "pair": "BTC/USDT:USDT", "tf_htf": "15m", "tf_ltf": "1m",
        "direction": "long", "timestamp": "2026-01-01T00:00:00Z",
        "entry": 100.0, "sl": 90.0, "tp": 130.0, "risk": 10.0,
        "rr": 3.0,    }
    sig.update(over)
    return Position(sig)


class ExcursionWindowTests(unittest.TestCase):
    def test_metrics_stop_at_the_exit_bar(self):
        # Fills at bar 1, reaches TP at bar 2, then collapses far below the
        # stop at bar 3. The collapse happened after the position closed.
        bars = [
            (105.0, 101.0),   # 0 signal bar
            (108.0,  99.0),   # 1 fill (low <= 100)
            (131.0, 120.0),   # 2 TP hit -> win
            (121.0,  70.0),   # 3 after exit: irrelevant to this trade
        ]
        ltf = ltf_frame(bars)
        p = make_position()
        p.set_signal_pos(0)
        p.try_fill(ltf, len(ltf) - 1, fill_window=10)
        self.assertTrue(p.filled)
        p.walk(ltf, len(ltf) - 1)
        self.assertEqual(p.outcome, "win")

        extend_win_paths([p], ltf)
        p.finalize(ltf)

        self.assertIsNotNone(p.mae_r)
        self.assertGreater(
            p.mae_r, -1.0,
            f"a win cannot have traded through its own stop (mae={p.mae_r})",
        )
        # Worst point during the trade is bar 1's low of 99 -> -0.1R.
        self.assertAlmostEqual(p.mae_r, -0.1, places=4)

    def test_winner_mfe_excludes_post_exit_spike(self):
        bars = [
            (105.0, 101.0),
            (108.0,  99.0),
            (131.0, 120.0),   # exit here at TP
            (400.0, 380.0),   # post-exit spike must not inflate MFE
        ]
        ltf = ltf_frame(bars)
        p = make_position()
        p.set_signal_pos(0)
        p.try_fill(ltf, len(ltf) - 1, fill_window=10)
        p.walk(ltf, len(ltf) - 1)
        extend_win_paths([p], ltf)
        p.finalize(ltf)
        # Highest point during the trade is 131 -> 3.1R, not 400.
        self.assertAlmostEqual(p.mfe_r, 3.1, places=4)

    def test_loser_metrics_are_unaffected(self):
        bars = [
            (105.0, 101.0),
            (108.0,  99.0),   # fill
            (102.0,  89.0),   # stop hit
        ]
        ltf = ltf_frame(bars)
        p = make_position()
        p.set_signal_pos(0)
        p.try_fill(ltf, len(ltf) - 1, fill_window=10)
        p.walk(ltf, len(ltf) - 1)
        p.finalize(ltf)
        self.assertEqual(p.outcome, "loss")
        self.assertAlmostEqual(p.mae_r, -1.1, places=4)

    def test_extension_still_available_for_the_rr_sweep(self):
        # The extended path must survive — the sweep depends on it.
        bars = [
            (105.0, 101.0), (108.0, 99.0), (131.0, 120.0), (121.0, 70.0),
        ]
        ltf = ltf_frame(bars)
        p = make_position()
        p.set_signal_pos(0)
        p.try_fill(ltf, len(ltf) - 1, fill_window=10)
        p.walk(ltf, len(ltf) - 1)
        before = len(p.path)
        extend_win_paths([p], ltf)
        self.assertGreater(len(p.path), before,
                           "sweep needs the post-exit path retained")


if __name__ == "__main__":
    unittest.main()
