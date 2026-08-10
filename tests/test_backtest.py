import unittest
from unittest.mock import patch

import pandas as pd

from analysis.backtest.scan_history import scan_pair_combo
from analysis.backtest.simulate import Position, simulate_group
from analysis.backtest.report import walk_path


def make_ltf(closes, index=None) -> pd.DataFrame:
    if index is None:
        index = pd.date_range("2026-01-01", periods=len(closes), freq="min", tz="UTC")
    lows = [min(c, closes[max(0, i - 1)]) * 0.995 for i, c in enumerate(closes)]
    highs = [max(c, closes[max(0, i - 1)]) * 1.005 for i, c in enumerate(closes)]
    return pd.DataFrame(
        {
            "Open": [closes[max(0, i - 1)] for i in range(len(closes))],
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [100.0] * len(closes),
        },
        index=index,
    )


def make_signal(ts, direction="long", entry=100.0, sl=95.0, tp=115.0, risk=5.0, rr=3.0):
    return {
        "timestamp": ts,
        "pair": "BTC/USDT:USDT",
        "tf_htf": "15m",
        "tf_ltf": "1m",
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "risk": risk,
        "rr": rr,
    }


class FillTests(unittest.TestCase):
    def test_long_limit_fills_when_price_trades_through_entry(self):
        index = pd.date_range("2026-01-01", periods=10, freq="min", tz="UTC")
        ltf = make_ltf([110, 109, 99, 105, 107, 108, 110, 112, 116, 118], index)
        signals = pd.DataFrame([make_signal(index[0])])
        positions = simulate_group(signals, ltf, fill_window=5)

        self.assertEqual(len(positions), 1)
        trade = positions[0]
        self.assertTrue(trade.filled)
        self.assertEqual(trade.outcome, "win")
        self.assertEqual(trade.r_multiple, 3.0)

    def test_short_limit_fills_when_price_trades_through_entry(self):
        index = pd.date_range("2026-01-01", periods=11, freq="min", tz="UTC")
        ltf = make_ltf([90, 91, 101, 99, 97, 96, 94, 92, 90, 88, 84], index)
        signals = pd.DataFrame([make_signal(index[0], direction="short", entry=100.0, sl=105.0, tp=85.0, risk=5.0)])
        positions = simulate_group(signals, ltf, fill_window=5)

        self.assertEqual(len(positions), 1)
        trade = positions[0]
        self.assertTrue(trade.filled)
        self.assertEqual(trade.outcome, "win")
        self.assertEqual(trade.r_multiple, 3.0)

    def test_unfilled_limit_expires_after_fill_window(self):
        index = pd.date_range("2026-01-01", periods=70, freq="min", tz="UTC")
        ltf = make_ltf([110, 109, 108, 107, 106, 105, 104, 103, 102, 101] + [100.5] * 60, index)
        signals = pd.DataFrame([make_signal(index[0])])
        positions = simulate_group(signals, ltf, fill_window=5)

        self.assertEqual(len(positions), 1)
        trade = positions[0]
        self.assertFalse(trade.filled)
        self.assertEqual(trade.outcome, "expired")


class WalkTests(unittest.TestCase):
    def test_sl_wins_when_same_candle_hits_both_sl_and_tp(self):
        index = pd.date_range("2026-01-01", periods=6, freq="min", tz="UTC")
        ltf = make_ltf([110, 109, 99, 105, 107, 108], index)
        ltf.loc[index[2], "Low"] = 94.0
        ltf.loc[index[2], "High"] = 120.0
        signals = pd.DataFrame([make_signal(index[0])])
        positions = simulate_group(signals, ltf, fill_window=5)

        trade = positions[0]
        self.assertEqual(trade.outcome, "loss")
        self.assertEqual(trade.r_multiple, -1.0)

    def test_one_position_rule_suppresses_signals_while_position_open(self):
        index = pd.date_range("2026-01-01", periods=9, freq="min", tz="UTC")
        ltf = make_ltf([110, 109, 99, 104, 106, 108, 112, 114, 116], index)
        signals = pd.DataFrame([
            make_signal(index[0]),
            make_signal(index[4]),
            make_signal(index[8]),
        ])
        positions = simulate_group(signals, ltf, fill_window=5)

        self.assertEqual(len(positions), 2)
        self.assertTrue(positions[0].filled)
        self.assertEqual(positions[0].outcome, "win")
        self.assertEqual(positions[1].outcome, "open")

    def test_long_no_fill_window_allows_next_signal(self):
        index = pd.date_range("2026-01-01", periods=29, freq="min", tz="UTC")
        ltf = make_ltf([110] + [100.6] * 6 + [99, 104, 106, 108] + [112, 116, 99, 112, 116, 118] * 3, index)
        signals = pd.DataFrame([make_signal(index[0]), make_signal(index[10])])
        positions = simulate_group(signals, ltf, fill_window=5)

        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0].outcome, "expired")
        self.assertTrue(positions[1].filled)
        self.assertEqual(positions[1].outcome, "win")


class SweepTests(unittest.TestCase):
    def make_filled_trade(self):
        return {
            "direction": "long",
            "entry": 100.0,
            "sl": 95.0,
            "tp": 115.0,
            "risk": 5.0,
            "filled": True,
            "path": [[108.0, 100.0], [115.0, 100.0], [120.0, 105.0], [104.0, 94.0]],
        }

    def test_walk_path_resolves_at_3r(self):
        result = walk_path(self.make_filled_trade(), 3.0)
        self.assertEqual(result["outcome"], "win")
        self.assertEqual(result["r"], 3.0)

    def test_walk_path_resolves_at_4r_after_original_tp(self):
        result = walk_path(self.make_filled_trade(), 4.0)
        self.assertEqual(result["outcome"], "win")
        self.assertEqual(result["r"], 4.0)

    def test_walk_path_loses_when_sl_comes_first(self):
        result = walk_path(self.make_filled_trade(), 5.0)
        self.assertEqual(result["outcome"], "loss")
        self.assertEqual(result["r"], -1.0)


class ScanDedupTests(unittest.TestCase):
    def test_same_fvg_is_only_emitted_once(self):
        index = pd.date_range("2026-01-01 00:00", periods=800, freq="min", tz="UTC")
        fake_setup = {
            "valid": True,
            "direction": "long",
            "entry": 100.0,
            "sl": 95.0,
            "tp": 115.0,
            "risk": 5.0,
            "rr": 3.0,
            "timestamp": None,
            "fvg_timestamp": index[30],
            "structure_htf": {"direction": "long", "kind": "CHOCH", "index": index[30]},
            "structure_ltf": None,        }

        class FakeStrategy:
            TIMEFRAME_DURATIONS = {"15m": pd.Timedelta(minutes=15), "1m": pd.Timedelta(minutes=1)}
            liquidation_enabled = False
            liquidation_leverage = 10.0

            @staticmethod
            def _htf_context(df_htf, direction):
                return (None, 1.0)

            def _check_direction(self, df_htf, df_ltf, direction, tf_htf="15m", tf_ltf="1m",
                                 htf_context=None, market_ctx=None):
                if direction != "long":
                    return {"valid": False}
                setup = dict(fake_setup)
                setup["timestamp"] = df_ltf.index[-1]
                return setup

        htf_df = pd.DataFrame(
            {"Open": [100.0] * 800, "High": [101.0] * 800, "Low": [99.0] * 800,
             "Close": [100.0] * 800, "Volume": [1.0] * 800},
            index=index,
        )
        ltf_df = htf_df.copy()

        with (
            patch("analysis.backtest.scan_history.AegisSMCStrategy", return_value=FakeStrategy()),
            patch("analysis.backtest.scan_history.db.get_cached_ohlcv",
                  side_effect=lambda symbol, tf, **kw: htf_df if tf == "15m" else ltf_df),
        ):
            signals = scan_pair_combo(("BTC/USDT:USDT", "15m", "1m", 30))

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["direction"], "long")


if __name__ == "__main__":
    unittest.main()
