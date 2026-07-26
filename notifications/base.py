from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class NotificationLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    TRADE = "trade"


LEVEL_EMOJI = {
    NotificationLevel.INFO: "ℹ️",
    NotificationLevel.WARNING: "⚠️",
    NotificationLevel.ERROR: "🚨",
    NotificationLevel.SUCCESS: "✅",
    NotificationLevel.TRADE: "💰",
}


class BaseNotifier(ABC):
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)

    @abstractmethod
    def send(self, message: str, level: NotificationLevel = NotificationLevel.INFO,
             **kwargs) -> bool:
        ...

    def format_message(self, message: str, level: NotificationLevel) -> str:
        emoji = LEVEL_EMOJI.get(level, "")
        return f"{emoji} {message}" if emoji else message
