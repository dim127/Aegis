from datetime import datetime, timedelta
from typing import List, Optional
import logging

from risk.base import IProtection, ProtectionResult

logger = logging.getLogger(__name__)


class LowProfitPairs(IProtection):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.lookback_days = self.config.get("lookback_days", 7)
        self.trade_limit = self.config.get("trade_limit", 3)
        self.stop_duration = timedelta(hours=self.config.get("stop_duration_hours", 24))
        self.required_profit = self.config.get("required_profit", 0.0)

    def check(self, *, pair: str = None, trades: List = None,
              current_time: datetime = None, **kwargs) -> ProtectionResult:
        trades = trades or []
        current_time = current_time or datetime.utcnow()
        pair_trades = [t for t in trades if t.get("pair") == pair and not t.get("is_open", True)]
        cutoff = current_time - timedelta(days=self.lookback_days)
        recent = [t for t in pair_trades if t.get("close_date", current_time) >= cutoff]

        if len(recent) >= self.trade_limit:
            total_profit = sum(t.get("profit_ratio", 0) for t in recent)
            if total_profit < self.required_profit:
                msg = (
                    f"LowProfitPairs: {pair} had {len(recent)} trades "
                    f"with {total_profit:.2%} profit (required: {self.required_profit:.2%})"
                )
                logger.warning(msg)
                return ProtectionResult(
                    stop=True,
                    reason=msg,
                    stop_duration=self.stop_duration,
                    pair=pair,
                )
        return ProtectionResult(stop=False)
