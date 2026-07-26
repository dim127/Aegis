from typing import List, Optional, Dict
import logging

from notifications.base import BaseNotifier, NotificationLevel
from notifications.telegram import TelegramNotifier
from notifications.webhook import WebhookNotifier
from notifications.discord import DiscordNotifier

logger = logging.getLogger(__name__)

NOTIFIER_MAP = {
    "telegram": TelegramNotifier,
    "webhook": WebhookNotifier,
    "discord": DiscordNotifier,
}


class NotificationManager:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.notifiers: List[BaseNotifier] = []
        self._build_notifiers()

    def _build_notifiers(self):
        notifier_configs = self.config.get("notifications", {})
        for name, ncfg in notifier_configs.items():
            notifier_class = NOTIFIER_MAP.get(name.lower())
            if notifier_class:
                self.notifiers.append(notifier_class(ncfg))
                logger.info(f"Notifier loaded: {name}")
            else:
                logger.warning(f"Unknown notifier: {name}")

    def send(self, message: str, level: NotificationLevel = NotificationLevel.INFO,
             **kwargs) -> Dict[str, bool]:
        results = {}
        for notifier in self.notifiers:
            try:
                success = notifier.send(message, level, **kwargs)
                results[notifier.__class__.__name__] = success
            except Exception as e:
                logger.error(f"Notification failed for {notifier.__class__.__name__}: {e}")
                results[notifier.__class__.__name__] = False
        return results

    def send_trade_entry(self, pair: str, price: float, side: str,
                         score: float = None, reason: str = None) -> Dict[str, bool]:
        results = {}
        for n in self.notifiers:
            try:
                if hasattr(n, "send_trade_entry"):
                    success = n.send_trade_entry(pair, price, side, score, reason)
                else:
                    msg = f"TRADE ENTRY - {pair} - {side.upper()} @ ${price:.4f}"
                    if score:
                        msg += f" (Score: {score})"
                    success = n.send(msg, NotificationLevel.TRADE)
                results[n.__class__.__name__] = success
            except Exception as e:
                logger.error(f"Trade entry notification failed: {e}")
                results[n.__class__.__name__] = False
        return results

    def send_trade_exit(self, pair: str, price: float, side: str, profit: float,
                        reason: str = None) -> Dict[str, bool]:
        results = {}
        for n in self.notifiers:
            try:
                if hasattr(n, "send_trade_exit"):
                    success = n.send_trade_exit(pair, price, side, profit, reason)
                else:
                    level = NotificationLevel.SUCCESS if profit > 0 else NotificationLevel.WARNING
                    msg = f"TRADE EXIT - {pair} - {side.upper()} @ ${price:.4f} - Profit: {profit:.2%}"
                    if reason:
                        msg += f" - {reason}"
                    success = n.send(msg, level)
                results[n.__class__.__name__] = success
            except Exception as e:
                logger.error(f"Trade exit notification failed: {e}")
                results[n.__class__.__name__] = False
        return results
