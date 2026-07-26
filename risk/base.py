from abc import ABC, abstractmethod
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class ProtectionResult:
    stop: bool = False
    reason: str = ""
    stop_duration: timedelta = timedelta(hours=1)
    pair: Optional[str] = None


class IProtection(ABC):
    def __init__(self, config: dict = None):
        self.config = config or {}

    @abstractmethod
    def check(self, *, pair: str = None, trades: List = None, current_time: datetime = None,
              current_profit: float = None, **kwargs) -> ProtectionResult:
        ...

    def reset(self):
        pass
