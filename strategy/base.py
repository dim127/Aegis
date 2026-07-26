from abc import ABC, abstractmethod
from typing import Dict, Optional
import pandas as pd


class IStrategy(ABC):

    timeframe: str = "1h"
    can_short: bool = True
    start_capital: float = 100.0
    max_open_trades: int = 3
    stake_amount: float = 30.0

    stoploss: float = -0.05
    trailing_stop: bool = False
    trailing_stop_positive: Optional[float] = None
    trailing_stop_positive_offset: float = 0.0
    trailing_only_offset_is_reached: bool = False

    use_custom_stoploss: bool = False
    use_exit_signal: bool = True
    use_entry_signal: bool = True

    position_adjustment_enable: bool = False
    max_entry_position_adjustment: int = 0

    @abstractmethod
    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    @abstractmethod
    def populate_entry_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    def populate_exit_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        df["exit_long"] = 0
        df["exit_short"] = 0
        return df

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
        return self.stoploss

    def custom_exit(
        self,
        pair: str,
        trade: "Trade",
        current_time: pd.Timestamp,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        return None

    def check_buy_timeout(
        self,
        pair: str,
        trade: "Trade",
        order: dict,
        current_time: pd.Timestamp,
        **kwargs,
    ) -> bool:
        return False

    def check_sell_timeout(
        self,
        pair: str,
        trade: "Trade",
        order: dict,
        current_time: pd.Timestamp,
        **kwargs,
    ) -> bool:
        return False

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: pd.Timestamp,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        return True

    def confirm_trade_exit(
        self,
        pair: str,
        trade: "Trade",
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: pd.Timestamp,
        **kwargs,
    ) -> bool:
        return True

    def leverage(
        self,
        pair: str,
        current_time: pd.Timestamp,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        side: str,
        **kwargs,
    ) -> float:
        return 1.0

    def minimal_roi(self, current_profit: float) -> Optional[float]:
        return None
