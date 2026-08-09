"""BUG-04: min_confluence must be able to reject something.

Three gates are mandatory — structure shift, fresh FVG, liquidity sweep — and
each contributes exactly one reason. So the count is >= 3 before the threshold
is ever consulted, and `min_confluence: 3` could never reject a setup. The
branch was dead.

The fix separates hard gates from soft ones and counts only the soft hits, so
the parameter describes something real. The default is chosen to preserve
current behaviour: confluence scored p=1.000 against outcomes over 79 trades,
so tightening it would cut signal volume without any evidence of improving
quality. Making the knob work is correctness; turning it up would be guessing.
"""
import unittest

import pandas as pd

from strategy.aegis_strategy import AegisSMCStrategy
from tests.test_smc_strategy import APPROVED_CONFIG, make_frame, structure_result


class SoftConfluenceCountTests(unittest.TestCase):
    def _strategy(self, min_soft=None):
        config = {**APPROVED_CONFIG}
        if min_soft is not None:
            config = {**config, "smc": {**APPROVED_CONFIG["smc"],
                                        "min_soft_confluence": min_soft}}
        return AegisSMCStrategy(exchange=object(), config=config)

    def test_hard_gates_are_named_and_disjoint_from_soft(self):
        s = self._strategy()
        self.assertEqual(len(s.HARD_FACTORS), 3)
        self.assertFalse(set(s.HARD_FACTORS) & set(s.SOFT_FACTORS))

    def test_soft_count_ignores_the_mandatory_three(self):
        s = self._strategy()
        # Only the three mandatory reasons present -> zero soft hits.
        self.assertEqual(s._count_soft(["structure", "fvg", "sweep"]), 0)

    def test_soft_count_tallies_optional_factors(self):
        s = self._strategy()
        hits = s._count_soft(["structure", "fvg", "sweep", "ob", "breakout"])
        self.assertEqual(hits, 2)

    def test_default_preserves_current_behaviour(self):
        # Default must not start rejecting setups that pass today, because no
        # evidence supports a tighter gate.
        s = self._strategy()
        self.assertEqual(s.min_soft_confluence, 0)

    def test_threshold_can_actually_reject(self):
        s = self._strategy(min_soft=2)
        self.assertEqual(s.min_soft_confluence, 2)
        self.assertLess(s._count_soft(["structure", "fvg", "sweep", "ob"]),
                        s.min_soft_confluence)

    def test_threshold_accepts_when_met(self):
        s = self._strategy(min_soft=2)
        self.assertGreaterEqual(
            s._count_soft(["structure", "fvg", "sweep", "ob", "cluster"]),
            s.min_soft_confluence,
        )


class GateRejectionIsReachableTests(unittest.TestCase):
    """The reject branch must execute, not merely exist."""

    def setUp(self):
        config = {**APPROVED_CONFIG,
                  "smc": {**APPROVED_CONFIG["smc"], "min_soft_confluence": 2}}
        self.strategy = AegisSMCStrategy(exchange=object(), config=config)
        self.df_htf = make_frame()
        self.df_ltf = make_frame()

    def _run(self, with_ob: bool, with_breakout: bool):
        fvg = {
            "index": self.df_ltf.index[-1],
            "displacement_index": self.df_ltf.index[-2],
            "direction": "long",
            "gap_low": 99.0, "gap_high": 101.0, "gap_mid": 100.0,
        }
        htf_event = {"direction": "long", "kind": "BOS",
                     "index": self.df_htf.index[-1], "level": 109.0}
        ob = {"index": self.df_htf.index[-2], "high": 100.5, "low": 99.5,
              "fully_mitigated": False, "mitigation_ratio": 0.0}
        from unittest.mock import patch
        with (
            patch("strategy.aegis_strategy.latest_structure_event",
                  return_value=structure_result(event=htf_event, bullish_bos=True)),
            patch("strategy.aegis_strategy.detect_structure", return_value=structure_result()),
            patch("strategy.aegis_strategy.fair_value_gaps",
                  return_value={"bullish_fvgs": [fvg], "bearish_fvgs": []}),
            patch("strategy.aegis_strategy.order_block_for_event",
                  return_value=ob if with_ob else None),
            patch("strategy.aegis_strategy.atr", return_value=pd.Series([1.0])),
            patch("strategy.aegis_strategy.is_fvg_mitigated", return_value=False),
            patch("strategy.aegis_strategy.is_breakout_candle", return_value=with_breakout),
            patch("strategy.aegis_strategy.liquidity_inflection", return_value=95.0),
            patch("strategy.aegis_strategy.detect_liquidity_sweep", return_value=True),
        ):
            return self.strategy._check_direction(self.df_htf, self.df_ltf, "long")

    def test_rejects_when_only_one_soft_factor_present(self):
        result = self._run(with_ob=True, with_breakout=False)
        self.assertFalse(result["valid"])
        self.assertIn("confluence", result["reason"].lower())

    def test_accepts_when_two_soft_factors_present(self):
        result = self._run(with_ob=True, with_breakout=True)
        self.assertTrue(result["valid"], result.get("reason"))


if __name__ == "__main__":
    unittest.main()
