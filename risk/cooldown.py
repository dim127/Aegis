from datetime import datetime, timedelta
from typing import List, Optional
import logging

from risk.base import IProtection, ProtectionResult

logger = logging.getLogger(__name__)


class CooldownPeriod(IProtection):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.cooldown_hours = self.config.get("cooldown_hours", 4)
        self.only_per_pair = self.config.get("only_per_pair", True)
        self._exits: dict[str, datetime] = {}

    def check(self, *, pair: str = None, trades: List = None,
              current_time: datetime = None, **kwargs) -> ProtectionResult:
        current_time = current_time or datetime.utcnow()
        if not pair:
            return ProtectionResult(stop=False)

        last_exit = self._exits.get(pair)
        if last_exit is not None:
            elapsed = current_time - last_exit
            if elapsed < timedelta(hours=self.cooldown_hours):
                remaining = timedelta(hours=self.cooldown_hours) - elapsed
                msg = (
                    f"CooldownPeriod: {pair} exited {elapsed} ago, "
                    f"wait {remaining} more"
                )
                return ProtectionResult(
                    stop=True,
                    reason=msg,
                    stop_duration=timedelta(hours=self.cooldown_hours),
                    pair=pair,
                )
        return ProtectionResult(stop=False)

    def record_exit(self, pair: str, time: datetime = None):
        self._exits[pair] = time or datetime.utcnow()
