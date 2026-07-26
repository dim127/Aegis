from typing import Optional, Dict
import pandas as pd
import numpy as np

from strategy.base import IStrategy
from indicators import (
    ema, rsi, macd, atr, vwap, volume_spike, detect_bos,
    order_blocks, fair_value_gaps, add_ta_indicators,
    btc_steering_filter, swing_highs, swing_lows, compute_scoring,
)
from config import SCORING_STRICT_THRESHOLD


class AegisStrategy(IStrategy):

    timeframe = "1h"
    can_short = True
    start_capital = 100.0
    max_open_trades = 3
    stake_amount = 30.0

    stoploss = -0.05
    use_custom_stoploss = True
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    scoring_threshold: float = 65.0
    atr_sl_multiplier: float = 1.5
    atr_tp_multiplier: float = 3.0
    rsi_oversold: float = 35.0
    rsi_overbought: float = 65.0
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 50

    scoring_weights: Dict[str, float] = None

    def __init__(self, **params):
        super().__init__()
        self.scoring_weights = {
            "technical": 40,
            "volume": 20,
            "market_structure": 20,
            "derivatives": 20,
            "sentiment": 10,
        }
        for k, v in params.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df_work = df.copy()
        df_work[f"EMA_{self.ema_fast}"] = ema(df_work["Close"], self.ema_fast)
        df_work[f"EMA_{self.ema_slow}"] = ema(df_work["Close"], self.ema_slow)
        df_work[f"EMA_{self.ema_trend}"] = ema(df_work["Close"], self.ema_trend)
        df_work["RSI_14"] = rsi(df_work["Close"], 14)
        macd(df_work)
        df_work["ATR_14"] = atr(df_work, 14)
        df_work["VWAP"] = vwap(df_work)
        df_work["Vol_24h_Avg"] = df_work["Volume"].rolling(24).mean()
        df_work["Volume_Spike"] = df_work.apply(
            lambda r: volume_spike(df_work.loc[:r.name]), axis=1
        )
        return df_work

    def populate_entry_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0
        df["enter_tag"] = ""

        df["score_long"] = np.nan
        df["score_short"] = np.nan

        default_bos = {"bullish_bos": False, "bearish_bos": False, "window_high": None, "window_low": None}

        for i in range(50, len(df)):
            row_slice = df.iloc[:i]
            recent = row_slice.tail(15)
            current_row = df.iloc[i]

            bos_info = detect_bos(row_slice, window=10)
            ob_info = order_blocks(row_slice, lookback=20)
            fvg_info = fair_value_gaps(row_slice, lookback=20)

            score_long, score_short, trend_up, trend_down = compute_scoring(
                current_row,
                fng_score=50,
                funding_rate=0.005,
                bos_info=bos_info,
                ob_info=ob_info,
                fvg_info=fvg_info,
            )

            df.loc[df.index[i], "score_long"] = score_long
            df.loc[df.index[i], "score_short"] = score_short

            if score_long >= self.scoring_threshold and not trend_down:
                df.loc[df.index[i], "enter_long"] = 1
                df.loc[df.index[i], "enter_tag"] = "aegis_long_score"

            elif score_short >= self.scoring_threshold and not trend_up:
                df.loc[df.index[i], "enter_short"] = 1
                df.loc[df.index[i], "enter_tag"] = "aegis_short_score"

        return df

    def populate_exit_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        df["exit_long"] = 0
        df["exit_short"] = 0
        df["exit_tag"] = ""

        for i in range(1, len(df)):
            prev_long = df["score_long"].iloc[i - 1] if i > 0 else 0
            prev_short = df["score_short"].iloc[i - 1] if i > 0 else 0
            curr_long = df["score_long"].iloc[i]
            curr_short = df["score_short"].iloc[i]

            if pd.notna(prev_long) and pd.notna(curr_long):
                if curr_long < self.scoring_threshold * 0.6 and prev_long >= self.scoring_threshold:
                    df.loc[df.index[i], "exit_long"] = 1
                    df.loc[df.index[i], "exit_tag"] = "score_drop_long"

            if pd.notna(prev_short) and pd.notna(curr_short):
                if curr_short < self.scoring_threshold * 0.6 and prev_short >= self.scoring_threshold:
                    df.loc[df.index[i], "exit_short"] = 1
                    df.loc[df.index[i], "exit_tag"] = "score_drop_short"

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
    ) -> Optional[float]:
        if current_profit > 0.03:
            return 0.01
        return self.stoploss

    def minimal_roi(self, current_profit: float) -> Optional[float]:
        if current_profit > 0.06:
            return 0.01
        elif current_profit > 0.03:
            return 0.02
        return None

    def custom_stake_amount(
        self,
        pair: str,
        current_time: pd.Timestamp,
        current_rate: float,
        proposed_stake: float,
        min_stake: float,
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        return proposed_stake
