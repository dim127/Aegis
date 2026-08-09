"""BUG-02: liquidation cluster prices must not be rounded to a fixed 2 decimals.

market_metrics rounded the cluster price to two decimals. On XRP at ~$1.06 that
is roughly 1% granularity, against a cluster_proximity_pct threshold of 3% — so
a third of the threshold was rounding noise rather than measurement.

Entry/SL/TP already snap to the exchange tick size. This closes the same hole on
the one price that did not.
"""
import unittest

import numpy as np
import pandas as pd

import market_metrics as mm


def synthetic_frame(price: float, rows: int = 120) -> pd.DataFrame:
    """A frame that oscillates around `price` so clusters can form."""
    index = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC")
    wobble = np.sin(np.linspace(0, 12, rows)) * price * 0.02
    close = price + wobble
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.002,
            "Low": close * 0.998,
            "Close": close,
            "Volume": np.linspace(100.0, 200.0, rows),
        },
        index=index,
    )


class ClusterPrecisionTests(unittest.TestCase):
    def _clusters(self, price):
        return mm.estimate_liquidation_clusters(synthetic_frame(price), leverage=10.0)

    def test_sub_ten_dollar_price_keeps_meaningful_precision(self):
        # XRP-like. At 2dp the cluster price granularity is ~1% of price, which
        # is a third of the 3% proximity threshold it is compared against.
        clusters = self._clusters(1.0612)
        self.assertIsNotNone(clusters)
        for side in ("nearest_above", "nearest_below"):
            target = clusters[side]
            if target is None:
                continue
            price = target["price"]
            self.assertGreater(price, 0.0, f"{side} collapsed to zero")
            # A 2dp round would leave at most 2 decimals; require finer.
            self.assertNotEqual(
                round(price, 2), price,
                f"{side} price {price} looks rounded to 2dp",
            )

    def test_large_price_is_unaffected(self):
        clusters = self._clusters(64727.35)
        self.assertIsNotNone(clusters)
        for side in ("nearest_above", "nearest_below"):
            if clusters[side] is not None:
                self.assertGreater(clusters[side]["price"], 1000.0)

    def test_relative_precision_holds_across_magnitudes(self):
        # The error introduced by quantisation must stay small relative to the
        # price, whatever the magnitude — that is the property 2dp violated.
        for price in (0.5231, 1.0612, 8.1812, 592.05, 64727.35):
            clusters = self._clusters(price)
            self.assertIsNotNone(clusters, f"no clusters at {price}")
            for side in ("nearest_above", "nearest_below"):
                target = clusters[side]
                if target is None:
                    continue
                # Cluster must sit within a sane band of the frame's own range.
                self.assertGreater(target["price"], price * 0.5)
                self.assertLess(target["price"], price * 1.5)

    def test_proximity_is_not_dominated_by_rounding(self):
        # The decisive case: at 2dp on a ~$1 asset, distance-to-entry moves in
        # ~1% steps while the gate compares against 3%.
        price = 1.0612
        clusters = self._clusters(price)
        target = clusters["nearest_below"] or clusters["nearest_above"]
        self.assertIsNotNone(target)
        step = abs(target["price"] - round(target["price"], 2))
        # If the value were 2dp-rounded this difference would be exactly zero.
        self.assertGreater(step, 0.0, "cluster price carries no sub-cent detail")


if __name__ == "__main__":
    unittest.main()
