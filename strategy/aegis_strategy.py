import pandas as pd
import numpy as np

from strategy.base import IStrategy
from indicators import add_ta_indicators, compute_multi_tf_scoring, check_15m_entry_confirmation
from config import SCORING_STRICT_THRESHOLD


class AegisStrategy(IStrategy):

    timeframe = "1h"
    can_short = True
    start_capital = 100.0
    max_open_trades = 3
    stake_amount = 30.0

    stoploss = -0.05
    use_custom_stoploss = True
    use_exit_signal = False

    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    scoring_threshold = float(SCORING_STRICT_THRESHOLD)
    use_15m_filter = True
    lookback_15m_hours = 24
    vary_fng_funding = True

    def __init__(self, **params):
        super().__init__()
        self.higher_tf_data = {}
        self.lower_tf_data = {}
        self.fng_score = 50
        self.funding_rate = 0.005
        self._rng = None
        for k, v in params.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        add_ta_indicators(df)
        for tf_df in self.higher_tf_data.values():
            if "ATRr_14" not in tf_df.columns:
                add_ta_indicators(tf_df)
        for tf_df in self.lower_tf_data.values():
            if "ATRr_14" not in tf_df.columns:
                add_ta_indicators(tf_df)
        return df

    def populate_entry_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0
        df["enter_tag"] = ""
        df["score_long"] = np.nan
        df["score_short"] = np.nan

        if self.vary_fng_funding and self._rng is None:
            pair = getattr(self, "_pair_name", "default")
            self._rng = np.random.default_rng(hash(pair) % (2**31))

        for i in range(100, len(df)):
            current_time = df.index[i]
            dfs_snapshot = {"1h": df.iloc[: i + 1]}
            for tf, tf_df in self.higher_tf_data.items():
                sliced = tf_df[tf_df.index <= current_time]
                if len(sliced) >= 50:
                    dfs_snapshot[tf] = sliced

            if self.vary_fng_funding and self._rng is not None:
                fng = int(np.clip(self._rng.normal(50, 15), 10, 95))
                fr = float(np.clip(self._rng.normal(0.005, 0.005), -0.02, 0.03))
            else:
                fng = self.fng_score
                fr = self.funding_rate

            score_long, score_short, trend_up, trend_down = compute_multi_tf_scoring(
                dfs_snapshot,
                fng_score=fng,
                funding_rate=fr,
            )

            idx = df.index[i]
            df.loc[idx, "score_long"] = score_long
            df.loc[idx, "score_short"] = score_short

            if score_long >= self.scoring_threshold and not trend_down:
                entry_price = df.loc[idx, "Close"]
                confirmed = self._check_15m_confirmation(current_time, entry_price, "long")
                if confirmed or not self.use_15m_filter:
                    df.loc[idx, "enter_long"] = 1
                    df.loc[idx, "enter_tag"] = "aegis_mtf_long_15m" if confirmed else "aegis_mtf_long"

            if score_short >= self.scoring_threshold and not trend_up:
                entry_price = df.loc[idx, "Close"]
                confirmed = self._check_15m_confirmation(current_time, entry_price, "short")
                if confirmed or not self.use_15m_filter:
                    df.loc[idx, "enter_short"] = 1
                    df.loc[idx, "enter_tag"] = "aegis_mtf_short_15m" if confirmed else "aegis_mtf_short"

        return df

    def _check_15m_confirmation(self, current_time: pd.Timestamp, entry_price: float, side: str) -> bool:
        if "15m" not in self.lower_tf_data:
            return True
        df_15m = self.lower_tf_data["15m"]
        lookback = pd.Timedelta(hours=self.lookback_15m_hours)
        start = current_time - lookback
        slice_15m = df_15m[(df_15m.index <= current_time) & (df_15m.index >= start)]
        if len(slice_15m) < 20:
            return True
        result = check_15m_entry_confirmation(slice_15m, entry_price, side)
        return result["confirmed"]

    def populate_exit_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        df["exit_long"] = 0
        df["exit_short"] = 0
        return df

    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: pd.Timestamp,
        current_rate: float,
        current_profit: float,
        after_fill: bool = False,
        **kwargs,
    ) -> float | None:
        if current_profit > 0.03:
            return 0.01
        return self.stoploss

    def minimal_roi(self, current_profit: float) -> float | None:
        return None
