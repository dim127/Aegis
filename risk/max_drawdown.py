from datetime import datetime, timedelta
from typing import List, Optional
import logging

from risk.base import IProtection, ProtectionResult

logger = logging.getLogger(__name__)


class MaxDrawdown(IProtection):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.max_drawdown = self.config.get("max_drawdown", 0.15)
        self.stop_duration = timedelta(hours=self.config.get("stop_duration_hours", 12))
        self.lookback_days = self.config.get("lookback_days", 30)
        self.trade_limit = self.config.get("trade_limit", None)
        self._starting_balance: Optional[float] = None
        self._peak_balance: Optional[float] = None

    def _current_drawdown(self) -> float:
        if self._peak_balance and self._peak_balance > 0:
            current = self._starting_balance or self._peak_balance
            return (self._peak_balance - current) / self._peak_balance
        return 0.0

    def update_balance(self, balance: float):
        if self._peak_balance is None or balance > self._peak_balance:
            self._peak_balance = balance
        if self._starting_balance is None:
            self._starting_balance = balance

    def check(self, *, pair: str = None, trades: List = None,
              current_time: datetime = None, **kwargs) -> ProtectionResult:
        dd = self._current_drawdown()
        if dd >= self.max_drawdown:
            trades_since = len([t for t in (trades or []) if not t.get("is_open", True)])
            if self.trade_limit is not None and trades_since < self.trade_limit:
                return ProtectionResult(stop=False)
            msg = (
                f"MaxDrawdown: {dd:.1%} drawdown reached (limit: {self.max_drawdown:.1%})"
            )
            logger.warning(msg)
            return ProtectionResult(
                stop=True,
                reason=msg,
                stop_duration=self.stop_duration,
            )
        return ProtectionResult(stop=False)

    def reset(self):
        self._starting_balance = None
        self._peak_balance = None
