import unittest
from unittest.mock import patch

import pandas as pd

from analysis.replay_smc import replay_closed_candles
from indicators import _ob_mitigation_ratio, detect_structure, is_fvg_mitigated, latest_structure_event, liquidity_inflection
from strategy.aegis_strategy import AegisSMCStrategy


APPROVED_CONFIG = {
    "smc_pairs": ["BTC", "ETH", "BNB", "SOL", "HYPE"],
    "smc": {"rr_target": 4.0, "atr_proximity": 2.0, "min_confluence": 3},
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

    def test_valid_setup_counts_only_the_five_official_factors(self):
        htf_event = {"direction": "long", "kind": "BOS", "index": self.df_15m.index[-1], "level": 109.0}
        htf = structure_result(event=htf_event, bullish_bos=True)
        ltf = structure_result()
        ob = {"index": self.df_15m.index[-2], "high": 105.0, "low": 100.0, "fully_mitigated": False, "mitigation_ratio": 0.0}

        with (
            patch("strategy.aegis_strategy.latest_structure_event", return_value=htf),
            patch("strategy.aegis_strategy.detect_structure", return_value=ltf),
            patch("strategy.aegis_strategy.fair_value_gaps", return_value={"bullish_fvgs": [self.fvg], "bearish_fvgs": []}),
            patch("strategy.aegis_strategy.order_block_for_event", return_value=ob),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([10.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.is_breakout_candle", return_value=True),
            patch("strategy.aegis_strategy.liquidity_inflection", return_value=95.0),
            patch("strategy.aegis_strategy.detect_liquidity_sweep", return_value=True),
        ):
            result = self.strategy._check_direction(self.df_15m, self.df_1m, "long")

        self.assertTrue(result["valid"])
        self.assertEqual(result["confluence"], 5)
        self.assertEqual(len(result["reasons"]), 5)
        self.assertEqual(result["rr"], 4.0)
        self.assertEqual(result["tp"], 192.5)
        self.assertEqual(result["management_rules"], "Hold until Stop Loss or Take Profit.")
        self.assertEqual(result["fvg_timestamp"], self.df_1m.index[-1])
        self.assertEqual(result["ob_timestamp"], self.df_15m.index[-2])

    def test_fresh_fvg_without_structure_shift_is_rejected(self):
        no_shift = structure_result()

        with (
            patch("strategy.aegis_strategy.latest_structure_event", return_value=no_shift),
            patch("strategy.aegis_strategy.detect_structure", return_value=no_shift),
            patch("strategy.aegis_strategy.fair_value_gaps", return_value={"bullish_fvgs": [self.fvg], "bearish_fvgs": []}),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([10.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.is_breakout_candle", return_value=True),
        ):
            result = self.strategy._check_direction(self.df_15m, self.df_1m, "long")

        self.assertFalse(result["valid"])
        self.assertIn("No structure shift", result["reason"])

    def test_fvg_before_structure_event_is_rejected(self):
        htf_event = {"direction": "long", "kind": "BOS", "index": self.df_15m.index[-1], "level": 109.0}
        old_fvg = {**self.fvg, "index": self.df_1m.index[-2]}

        with (
            patch("strategy.aegis_strategy.latest_structure_event", return_value=structure_result(event=htf_event, bullish_bos=True)),
            patch("strategy.aegis_strategy.detect_structure", return_value=structure_result()),
            patch("strategy.aegis_strategy.fair_value_gaps", return_value={"bullish_fvgs": [old_fvg], "bearish_fvgs": []}),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([10.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.is_breakout_candle", return_value=True),
        ):
            result = self.strategy._check_direction(self.df_15m, self.df_1m, "long")

        self.assertFalse(result["valid"])
        self.assertIn("No valid FVG", result["reason"])

    def test_config_cannot_reduce_minimum_rr(self):
        invalid_config = {**APPROVED_CONFIG, "smc": {**APPROVED_CONFIG["smc"], "rr_target": 2.0}}

        with self.assertRaisesRegex(ValueError, "rr_target"):
            AegisSMCStrategy(exchange=object(), config=invalid_config)


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

        def check_direction(df_15m, df_1m, direction):
            received_lengths.append((len(df_15m), len(df_1m), direction))
            return {"valid": False}

        with patch.object(strategy, "_check_direction", side_effect=check_direction):
            replay_closed_candles(strategy, raw_15m, raw_1m, [pd.Timestamp("2026-01-01 12:50:30Z")])

        self.assertEqual(received_lengths, [(51, 50, "long"), (51, 50, "short")])


if __name__ == "__main__":
    unittest.main()
