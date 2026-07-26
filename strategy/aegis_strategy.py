import pandas as pd
import numpy as np

from strategy.base import IStrategy
from indicators import add_ta_indicators, compute_multi_tf_scoring
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

    def __init__(self, **params):
        super().__init__()
        self.higher_tf_data = {}
        self.fng_score = 50
        self.funding_rate = 0.005
        for k, v in params.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        add_ta_indicators(df)
        for tf_df in self.higher_tf_data.values():
            if "ATRr_14" not in tf_df.columns:
                add_ta_indicators(tf_df)
        return df

    def populate_entry_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0
        df["enter_tag"] = ""
        df["score_long"] = np.nan
        df["score_short"] = np.nan

        for i in range(100, len(df)):
            current_time = df.index[i]
            dfs_snapshot = {"1h": df.iloc[: i + 1]}
            for tf, tf_df in self.higher_tf_data.items():
                sliced = tf_df[tf_df.index <= current_time]
                if len(sliced) >= 50:
                    dfs_snapshot[tf] = sliced

            score_long, score_short, trend_up, trend_down = compute_multi_tf_scoring(
                dfs_snapshot,
                fng_score=self.fng_score,
                funding_rate=self.funding_rate,
            )

            idx = df.index[i]
            df.loc[idx, "score_long"] = score_long
            df.loc[idx, "score_short"] = score_short

            if score_long >= self.scoring_threshold and not trend_down:
                df.loc[idx, "enter_long"] = 1
                df.loc[idx, "enter_tag"] = "aegis_mtf_long"
            elif score_short >= self.scoring_threshold and not trend_up:
                df.loc[idx, "enter_short"] = 1
                df.loc[idx, "enter_tag"] = "aegis_mtf_short"

        return df

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
