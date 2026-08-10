import unittest
from unittest.mock import patch

import pandas as pd

from analysis.replay_smc import replay_closed_candles
from indicators import _ob_mitigation_ratio, detect_structure, is_fvg_mitigated, latest_structure_event, liquidity_inflection
from indicators import ote_zone
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


class ICTSequenceTests(unittest.TestCase):
    """POI -> retracement -> sweep -> MSS -> OTE entry, in that order.

    The two timeframes do different jobs: HTF gives the zone, LTF gives the
    confirmation. Each gate is binary and rejections name the step that failed,
    so a setup that does not appear is always explicable.
    """

    def setUp(self):
        self.strategy = AegisSMCStrategy(exchange=object(), config=APPROVED_CONFIG)
        # LTF that sweeps down to 90 then recovers, so a long is plausible.
        idx = pd.date_range("2026-01-01", periods=80, freq="min", tz="UTC")
        close = [100.0] * 60 + [95.0] * 5 + [104.0] * 15
        self.df_ltf = pd.DataFrame(
            {"Open": close, "High": [c + 1 for c in close],
             "Low": [c - 1 for c in close], "Close": close,
             "Volume": [100.0] * 80}, index=idx)
        self.df_htf = self.df_ltf.copy()
        self.poi = {"index": self.df_htf.index[-30], "displacement_index": self.df_htf.index[-31],
                    "direction": "long", "gap_low": 88.0, "gap_high": 96.0, "gap_mid": 92.0}
        self.sweep = {"price": 92.0, "index": self.df_ltf.index[-18],
                      "swept_level": 94.0}
        self.entry_fvg = {"index": self.df_ltf.index[-6],
                          "displacement_index": self.df_ltf.index[-7],
                          "direction": "long", "gap_low": 96.0,
                          "gap_high": 98.0, "gap_mid": 97.0}

    def _run(self, poi=True, retraced=True, sweep=True, sweep_inside=True,
             mss=True, mss_after=True, entry_fvg=True):
        sweep_pos = self.df_ltf.index.get_loc(self.sweep["index"])
        event = {"direction": "long", "kind": "CHOCH",
                 "index": self.df_ltf.index[-10 if mss_after else -25], "level": 104.0,
                 "broken_swing_index": self.df_ltf.index[sweep_pos + 2]}
        ltf_struct = structure_result(event=event if mss else None, bullish_choch=mss)
        htf_struct = structure_result()
        sweep_obj = dict(self.sweep)
        if not sweep_inside:
            sweep_obj["price"] = 70.0
        # "Not retraced" means the zone sits far from where price has traded,
        # so move the POI rather than the frame.
        poi_obj = dict(self.poi)
        if not retraced:
            poi_obj.update(gap_low=500.0, gap_high=510.0, gap_mid=505.0)
        htf_frame = self.df_htf
        with (
            patch("strategy.aegis_strategy.latest_structure_event", return_value=htf_struct),
            patch("strategy.aegis_strategy.detect_structure", return_value=ltf_struct),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([1.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.find_liquidity_sweep",
                  return_value=sweep_obj if sweep else None),
            patch("strategy.aegis_strategy.liquidity_target", return_value=None),
            patch("strategy.aegis_strategy.fair_value_gaps") as fvgs,
        ):
            fvgs.side_effect = lambda df, **kw: (
                {"bullish_fvgs": [poi_obj] if poi else [], "bearish_fvgs": []}
                if df is htf_frame else
                {"bullish_fvgs": [self.entry_fvg] if entry_fvg else [], "bearish_fvgs": []}
            )
            return self.strategy._check_direction(htf_frame, self.df_ltf, "long")

    def test_missing_poi_rejects_first(self):
        r = self._run(poi=False)
        self.assertFalse(r["valid"])
        self.assertIn("POI", r["reason"])

    def test_price_must_retrace_into_the_poi(self):
        r = self._run(retraced=False)
        self.assertFalse(r["valid"])
        self.assertIn("retraced", r["reason"])

    def test_no_sweep_rejects(self):
        self.assertIn("sweep", self._run(sweep=False)["reason"])

    def test_sweep_outside_the_poi_rejects(self):
        # The sweep has to happen inside the zone; one elsewhere is a different
        # event that says nothing about this POI.
        r = self._run(sweep_inside=False)
        self.assertFalse(r["valid"])
        self.assertIn("outside", r["reason"])

    def test_missing_mss_rejects(self):
        self.assertIn("MSS", self._run(mss=False)["reason"])

    def test_mss_before_the_sweep_rejects(self):
        # Confirmation cannot precede what it confirms.
        r = self._run(mss_after=False)
        self.assertFalse(r["valid"])
        self.assertIn("did not follow", r["reason"])

    def test_htf_needs_no_mss_of_its_own(self):
        # The regression that motivated this design: HTF supplies the zone, and
        # requiring a shift there rejected everything.
        r = self._run()
        self.assertTrue(r["valid"], r.get("reason"))

    def test_entry_sits_in_the_ote_band(self):
        r = self._run()
        self.assertTrue(r["valid"], r.get("reason"))
        self.assertGreaterEqual(r["entry"], r["ote_low"])
        self.assertLessEqual(r["entry"], r["ote_high"])

    def test_stop_sits_behind_the_sweep(self):
        r = self._run()
        self.assertLess(r["sl"], r["sweep_price"])

    def test_no_score_fields_remain(self):
        r = self._run()
        for gone in ("confluence", "soft_hits", "reasons", "rr_net", "context"):
            self.assertNotIn(gone, r)

    def test_identical_input_gives_identical_output(self):
        self.assertEqual(self._run(), self._run())


class OteZoneTests(unittest.TestCase):
    def test_long_ote_is_the_discount_band(self):
        low, high = ote_zone(100.0, 200.0, "long")
        self.assertAlmostEqual(low, 121.4)    # 200 - 78.6%
        self.assertAlmostEqual(high, 138.2)   # 200 - 61.8%

    def test_short_ote_is_the_premium_band(self):
        low, high = ote_zone(100.0, 200.0, "short")
        self.assertAlmostEqual(low, 161.8)
        self.assertAlmostEqual(high, 178.6)

    def test_degenerate_leg_returns_the_leg(self):
        self.assertEqual(ote_zone(100.0, 100.0, "long"), (100.0, 100.0))


class MssMustBreakTheSweepLegTests(unittest.TestCase):
    """The MSS has to break a swing the sweep produced.

    Ordering alone is not confirmation: a break of some older, unrelated swing
    that merely happens after the sweep shares a direction and a timestamp with
    the reversal and nothing else.
    """

    def setUp(self):
        base = ICTSequenceTests("test_htf_needs_no_mss_of_its_own")
        base.setUp()
        self.base = base

    def _run(self, broken_offset):
        b = self.base
        sweep_idx = b.sweep["index"]
        broken = (b.df_ltf.index[b.df_ltf.index.get_loc(sweep_idx) + broken_offset]
                  if broken_offset is not None else None)
        event = {"direction": "long", "kind": "CHOCH",
                 "index": b.df_ltf.index[-10], "level": 104.0,
                 "broken_swing_index": broken}
        ltf_struct = structure_result(event=event, bullish_choch=True)
        with (
            patch("strategy.aegis_strategy.latest_structure_event",
                  return_value=structure_result()),
            patch("strategy.aegis_strategy.detect_structure", return_value=ltf_struct),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([1.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.find_liquidity_sweep", return_value=dict(b.sweep)),
            patch("strategy.aegis_strategy.liquidity_target", return_value=None),
            patch("strategy.aegis_strategy.fair_value_gaps") as fvgs,
        ):
            fvgs.side_effect = lambda df, **kw: (
                {"bullish_fvgs": [b.poi], "bearish_fvgs": []}
                if df is b.df_htf else
                {"bullish_fvgs": [b.entry_fvg], "bearish_fvgs": []}
            )
            return b.strategy._check_direction(b.df_htf, b.df_ltf, "long")

    def test_breaking_a_swing_after_the_sweep_is_valid(self):
        r = self._run(broken_offset=2)
        self.assertTrue(r["valid"], r.get("reason"))

    def test_breaking_an_older_swing_is_rejected(self):
        r = self._run(broken_offset=-5)
        self.assertFalse(r["valid"])
        self.assertIn("older than the sweep", r["reason"])

    def test_no_broken_swing_recorded_is_rejected(self):
        r = self._run(broken_offset=None)
        self.assertFalse(r["valid"])


if __name__ == "__main__":
    unittest.main()
