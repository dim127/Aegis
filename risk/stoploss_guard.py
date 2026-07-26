from datetime import datetime, timedelta
from typing import List, Optional
import logging

from risk.base import IProtection, ProtectionResult

logger = logging.getLogger(__name__)


class StoplossGuard(IProtection):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.lookback_period = timedelta(hours=self.config.get("lookback_hours", 24))
        self.trade_limit = self.config.get("trade_limit", 3)
        self.stop_duration = timedelta(hours=self.config.get("stop_duration_hours", 4))
        self.required_profit = self.config.get("required_profit", 0.0)
        self.only_per_pair = self.config.get("only_per_pair", False)
        self._stoploss_history: List[dict] = []

    def check(self, *, pair: str = None, trades: List = None,
              current_time: datetime = None, **kwargs) -> ProtectionResult:
        trades = trades or []
        current_time = current_time or datetime.utcnow()

        cutoff = current_time - self.lookback_period
        if self.only_per_pair and pair:
            recent = [
                t for t in self._stoploss_history
                if t["time"] >= cutoff and t["pair"] == pair
            ]
        else:
            recent = [t for t in self._stoploss_history if t["time"] >= cutoff]

        if len(recent) >= self.trade_limit:
            msg = (
                f"StoplossGuard: {len(recent)} stoplosses in {self.lookback_period}"
                f"{' for ' + pair if self.only_per_pair else ''} — stopping trades"
            )
            logger.warning(msg)
            return ProtectionResult(
                stop=True,
                reason=msg,
                stop_duration=self.stop_duration,
                pair=pair if self.only_per_pair else None,
            )
        return ProtectionResult(stop=False)

    def record_stoploss(self, pair: str, profit: float, time: datetime = None):
        self._stoploss_history.append({
            "pair": pair,
            "profit": profit,
            "time": time or datetime.utcnow(),
        })
