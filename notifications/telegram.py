import logging
from typing import Optional

from notifications.base import BaseNotifier, NotificationLevel

logger = logging.getLogger(__name__)


class TelegramNotifier(BaseNotifier):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.bot_token = self.config.get("bot_token", "")
        self.chat_id = self.config.get("chat_id", "")
        self._base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    def send(self, message: str, level: NotificationLevel = NotificationLevel.INFO,
             **kwargs) -> bool:
        if not self.enabled or not self._base_url:
            return False
        try:
            import httpx
            formatted = self.format_message(message, level)
            payload = {
                "chat_id": self.chat_id,
                "text": formatted,
                "parse_mode": kwargs.get("parse_mode", "HTML"),
                "disable_web_page_preview": True,
            }
            with httpx.Client(timeout=10) as client:
                res = client.post(f"{self._base_url}/sendMessage", json=payload)
                res.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_trade_entry(self, pair: str, price: float, side: str, score: float = None,
                         reason: str = None) -> bool:
        msg = (
            f"<b>TRADE ENTRY</b>\n"
            f"Pair: {pair}\n"
            f"Side: {side.upper()}\n"
            f"Price: ${price:.4f}\n"
        )
        if score is not None:
            msg += f"Score: {score}/100\n"
        if reason:
            msg += f"Reason: {reason}"
        return self.send(msg, NotificationLevel.TRADE)

    def send_trade_exit(self, pair: str, price: float, side: str, profit: float,
                        reason: str = None) -> bool:
        emoji = "🟢" if profit > 0 else "🔴"
        msg = (
            f"{emoji} <b>TRADE EXIT</b>\n"
            f"Pair: {pair}\n"
            f"Side: {side.upper()}\n"
            f"Exit Price: ${price:.4f}\n"
            f"Profit: {profit:.2%}\n"
        )
        if reason:
            msg += f"Reason: {reason}"
        level = NotificationLevel.SUCCESS if profit > 0 else NotificationLevel.WARNING
        return self.send(msg, level)
