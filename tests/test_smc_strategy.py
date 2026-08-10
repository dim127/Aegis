import unittest
from unittest.mock import patch

import pandas as pd

from analysis.replay_smc import replay_closed_candles
from indicators import _ob_mitigation_ratio, detect_structure, is_fvg_mitigated, latest_structure_event, liquidity_inflection
from strategy.aegis_strategy import AegisSMCStrategy


APPROVED_CONFIG = {
    "smc_pairs": ["BTC", "ETH", "BNB", "SOL", "HYPE"],
    "smc": {"rr_target": 3.0, "sl_atr_buffer": 1.5},
}


def make_frame(rows: int = 50) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="min")
    return pd.DataFrame(
        {
            "Open": [109.0] * rows,
            "High": [111.0] * rows,
            "Low": [108.0] * rows,
            "Close": [110.0] * rows,
            "Volume": [100.0] * rows,
        },
        index=index,
    )


def to_raw(df: pd.DataFrame) -> list:
    return [
        [int(timestamp.timestamp() * 1000), row.Open, row.High, row.Low, row.Close, row.Volume]
        for timestamp, row in df.iterrows()
    ]


def structure_result(event=None, bullish_choch=False, bullish_bos=False):
    return {
        "bullish_choch": bullish_choch,
        "bearish_choch": False,
        "bullish_bos": bullish_bos,
        "bearish_bos": False,
        "last_swing_high": 109.0,
        "last_swing_low": 90.0,
        "event": event,
    }


class FvgAndOrderBlockTests(unittest.TestCase):
    def test_fvg_is_fresh_until_a_later_candle_enters_it(self):
        df = pd.DataFrame(
            {
                "Open": [95, 100, 106, 108],
                "High": [100, 108, 112, 111],
                "Low": [90, 98, 105, 106],
                "Close": [98, 106, 110, 109],
                "Volume": [1, 1, 1, 1],
            },
            index=pd.date_range("2026-01-01", periods=4, freq="min"),
        )

        self.assertFalse(is_fvg_mitigated(df, 100, 105, df.index[2]))
        df.loc[df.index[3], "Low"] = 104
        self.assertTrue(is_fvg_mitigated(df, 100, 105, df.index[2]))

    def test_ob_mitigation_includes_the_latest_candle(self):
        df = pd.DataFrame(
            {
                "Open": [100, 100, 103],
                "High": [101, 105, 106],
                "Low": [99, 100, 102],
                "Close": [100, 101, 105],
                "Volume": [1, 1, 1],
            }
        )

        mitigation = _ob_mitigation_ratio(df, -2, 100, 104)
        self.assertTrue(mitigation["mitigated"])
        self.assertEqual(mitigation["mitigation_ratio"], 0.5)

    def test_confirmed_bearish_swings_turn_bullish_break_into_choch(self):
        df = make_frame(30)
        df.loc[:, ["Open", "High", "Low", "Close"]] = [97.0, 100.0, 95.0, 97.0]
        df.loc[df.index[16], ["High", "Low"]] = [110.0, 100.0]
        df.loc[df.index[19], ["High", "Low"]] = [95.0, 90.0]
        df.loc[df.index[22], ["High", "Low"]] = [105.0, 96.0]
        df.loc[df.index[25], ["High", "Low"]] = [92.0, 85.0]
        df.loc[df.index[29], ["Open", "High", "Low", "Close"]] = [100.0, 116.0, 99.0, 115.0]

        structure = detect_structure(df, window=15)

        self.assertTrue(structure["bullish_choch"])
        self.assertFalse(structure["bullish_bos"])
        self.assertEqual(structure["event"]["kind"], "CHOCH")
        self.assertEqual(structure["event"]["broken_swing_index"], df.index[22])
        self.assertEqual(liquidity_inflection(df, "long", before=df.index[29]), 85.0)

        later = make_frame(3).set_axis(pd.date_range("2026-01-01 00:30", periods=3, freq="min"))
        extended = pd.concat([df, later])
        latest = latest_structure_event(extended, "long", window=15)
        self.assertEqual(latest["event"]["index"], df.index[29])


class StrategyRuleTests(unittest.TestCase):
    def setUp(self):
        self.strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)
        self.df_15m = make_frame()
        self.df_1m = make_frame()
        self.fvg = {
            "index": self.df_1m.index[-1],
            "displacement_index": self.df_1m.index[-2],
            "direction": "long",
            "gap_low": 100.0,
            "gap_high": 105.0,
            "gap_mid": 102.5,
        }

    def test_exchange_is_saved_when_injected(self):
        with patch("strategy.aegis_strategy.ccxt.hyperliquid") as mock_cls:
            strategy = AegisSMCStrategy(exchange="fake", config=APPROVED_CONFIG)
        mock_cls.assert_not_called()
        self.assertEqual(strategy.exchange, "fake")

    def test_exchange_is_created_when_none(self):
        with patch("strategy.aegis_strategy.ccxt.hyperliquid") as mock_cls:
            strategy = AegisSMCStrategy(exchange=None, config=APPROVED_CONFIG)
        mock_cls.assert_called_once()
        self.assertEqual(strategy.exchange, mock_cls.return_value)





class ClosedCandleReplayTests(unittest.TestCase):
    def test_conversion_excludes_open_candle(self):
        strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)
        index = pd.date_range("2026-01-01 12:00", periods=51, freq="min", tz="UTC")
        raw = to_raw(make_frame(51).set_axis(index))

        completed = strategy._ohlcv_to_df(raw, "1m", now=pd.Timestamp("2026-01-01 12:50:30Z"))

        self.assertEqual(len(completed), 50)
        self.assertEqual(completed.index[-1], pd.Timestamp("2026-01-01 12:49:00Z"))

    def test_replay_never_passes_an_open_1m_candle_to_strategy(self):
        strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)
        one_minute_index = pd.date_range("2026-01-01 12:00", periods=51, freq="min", tz="UTC")
        fifteen_minute_index = pd.date_range("2026-01-01 00:00", periods=51, freq="15min", tz="UTC")
        raw_1m = to_raw(make_frame(51).set_axis(one_minute_index))
        raw_15m = to_raw(make_frame(51).set_axis(fifteen_minute_index))
        received_lengths = []

        def check_direction(df_15m, df_1m, direction, tf_htf="15m", tf_ltf="1m"):
            received_lengths.append((len(df_15m), len(df_1m), direction))
            return {"valid": False}

        with patch.object(strategy, "_check_direction", side_effect=check_direction):
            replay_closed_candles(strategy, raw_15m, raw_1m, [pd.Timestamp("2026-01-01 12:50:30Z")])

        self.assertEqual(received_lengths, [(51, 50, "long"), (51, 50, "short")])


if __name__ == "__main__":
    unittest.main()


class PureDetectionTests(unittest.TestCase):
    """All five conditions required, nothing scored.

    The gates are checked in order, and each rejection names the one that failed
    — so a setup that does not appear can always be explained, rather than being
    the silent result of a score landing under some threshold.
    """

    def setUp(self):
        self.strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)
        self.df_htf = make_frame()
        self.df_ltf = make_frame()
        self.fvg = {
            "index": self.df_ltf.index[-1],
            "displacement_index": self.df_ltf.index[-2],
            "direction": "long",
            "gap_low": 100.0, "gap_high": 105.0, "gap_mid": 102.5,
        }

    def _run(self, htf_shift=True, ltf_shift=True, fvg=True, sweep=True, swing=95.0):
        event = {"direction": "long", "kind": "CHOCH",
                 "index": self.df_htf.index[-1], "level": 109.0}
        htf = structure_result(event=event if htf_shift else None,
                               bullish_choch=htf_shift)
        ltf = structure_result(event=event if ltf_shift else None,
                               bullish_choch=ltf_shift)
        with (
            patch("strategy.aegis_strategy.latest_structure_event", return_value=htf),
            patch("strategy.aegis_strategy.detect_structure", return_value=ltf),
            patch("strategy.aegis_strategy.fair_value_gaps",
                  return_value={"bullish_fvgs": [self.fvg] if fvg else [],
                                "bearish_fvgs": []}),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([1.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.detect_liquidity_sweep", return_value=sweep),
            patch("strategy.aegis_strategy.liquidity_inflection", return_value=swing),
            patch("strategy.aegis_strategy.liquidity_target", return_value=None),
        ):
            return self.strategy._check_direction(self.df_htf, self.df_ltf, "long")

    def test_all_five_conditions_produce_a_setup(self):
        r = self._run()
        self.assertTrue(r["valid"], r.get("reason"))
        self.assertEqual(r["entry"], 102.5)

    def test_htf_alone_is_not_enough(self):
        # The confluence requirement: an LTF break without HTF agreement, or
        # vice versa, is not a setup.
        r = self._run(ltf_shift=False)
        self.assertFalse(r["valid"])
        self.assertIn("No MSS on 1m", r["reason"])

    def test_ltf_alone_is_not_enough(self):
        r = self._run(htf_shift=False)
        self.assertFalse(r["valid"])
        self.assertIn("No MSS on 15m", r["reason"])

    def test_missing_fvg_rejects(self):
        self.assertIn("FVG", self._run(fvg=False)["reason"])

    def test_missing_sweep_rejects(self):
        self.assertIn("sweep", self._run(sweep=False)["reason"])

    def test_missing_swing_rejects(self):
        self.assertIn("swing", self._run(swing=None)["reason"])

    def test_no_score_or_threshold_fields_remain(self):
        r = self._run()
        for gone in ("confluence", "soft_hits", "reasons", "rr_net", "context"):
            self.assertNotIn(gone, r, f"{gone} should no longer exist")

    def test_identical_input_gives_identical_output(self):
        # Determinism is the property scoring cost us.
        self.assertEqual(self._run(), self._run())


class LiquidityTargetTests(unittest.TestCase):
    """R follows from where the swings are, rather than being chosen."""

    def setUp(self):
        self.strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)
        self.df_htf = make_frame()
        self.df_ltf = make_frame()

    def _run(self, target):
        event = {"direction": "long", "kind": "BOS",
                 "index": self.df_htf.index[-1], "level": 109.0}
        st = structure_result(event=event, bullish_bos=True)
        fvg = {"index": self.df_ltf.index[-1], "displacement_index": self.df_ltf.index[-2],
               "direction": "long", "gap_low": 99.0, "gap_high": 101.0, "gap_mid": 100.0}
        with (
            patch("strategy.aegis_strategy.latest_structure_event", return_value=st),
            patch("strategy.aegis_strategy.detect_structure", return_value=st),
            patch("strategy.aegis_strategy.fair_value_gaps",
                  return_value={"bullish_fvgs": [fvg], "bearish_fvgs": []}),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([0.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.detect_liquidity_sweep", return_value=True),
            patch("strategy.aegis_strategy.liquidity_inflection", return_value=90.0),
            patch("strategy.aegis_strategy.liquidity_target", return_value=target),
        ):
            return self.strategy._check_direction(self.df_htf, self.df_ltf, "long")

    def test_rr_is_derived_from_the_swing(self):
        # entry 100, stop 90 -> risk 10; a swing at 125 is 2.5R, not 3R.
        r = self._run(125.0)
        self.assertTrue(r["valid"])
        self.assertEqual(r["tp"], 125.0)
        self.assertAlmostEqual(r["rr"], 2.5)
        self.assertEqual(r["tp_source"], "swing")

    def test_a_distant_swing_gives_a_larger_r(self):
        r = self._run(160.0)
        self.assertAlmostEqual(r["rr"], 6.0)

    def test_falls_back_to_the_multiple_without_a_swing(self):
        r = self._run(None)
        self.assertEqual(r["tp_source"], "multiple")
        self.assertAlmostEqual(r["rr"], 3.0)

    def test_a_target_on_the_wrong_side_is_rejected(self):
        r = self._run(95.0)
        self.assertFalse(r["valid"])
        self.assertIn("wrong side", r["reason"])
