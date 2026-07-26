import json
import logging
from typing import Optional

from notifications.base import BaseNotifier, NotificationLevel

logger = logging.getLogger(__name__)

LEVEL_COLORS = {
    NotificationLevel.INFO: 5814783,
    NotificationLevel.WARNING: 16763904,
    NotificationLevel.ERROR: 15548997,
    NotificationLevel.SUCCESS: 5763719,
    NotificationLevel.TRADE: 15844367,
}


class DiscordNotifier(BaseNotifier):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.webhook_url = self.config.get("webhook_url", "")
        self.username = self.config.get("username", "Aegis Bot")
        self.avatar_url = self.config.get("avatar_url", "")

    def send(self, message: str, level: NotificationLevel = NotificationLevel.INFO,
             **kwargs) -> bool:
        if not self.enabled or not self.webhook_url:
            return False
        try:
            import httpx
            embed = {
                "title": level.value.upper(),
                "description": self.format_message(message, level),
                "color": LEVEL_COLORS.get(level, 5814783),
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            }
            payload = {
                "username": self.username,
                "embeds": [embed],
            }
            if self.avatar_url:
                payload["avatar_url"] = self.avatar_url
            payload.update(kwargs.get("extra", {}))

            with httpx.Client(timeout=10) as client:
                res = client.post(self.webhook_url, json=payload)
                res.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Discord send failed: {e}")
            return False

    def send_trade(self, pair: str, side: str, entry_price: float, exit_price: float = None,
                   profit: float = None, score: float = None) -> bool:
        if exit_price is not None and profit is not None:
            emoji = "🟢" if profit > 0 else "🔴"
            title = f"{emoji} Trade Closed: {pair}"
            desc = (
                f"**Side:** {side.upper()}\n"
                f"**Entry:** ${entry_price:.4f}\n"
                f"**Exit:** ${exit_price:.4f}\n"
                f"**Profit:** {profit:.2%}\n"
            )
        else:
            title = f"💰 Trade Opened: {pair}"
            desc = (
                f"**Side:** {side.upper()}\n"
                f"**Entry:** ${entry_price:.4f}\n"
            )
            if score is not None:
                desc += f"**Score:** {score}/100\n"
        embed = {
            "title": title,
            "description": desc,
            "color": LEVEL_COLORS[NotificationLevel.SUCCESS if (profit or 0) >= 0 else NotificationLevel.ERROR],
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        }
        payload = {"username": self.username, "embeds": [embed]}
        try:
            import httpx
            with httpx.Client(timeout=10) as client:
                res = client.post(self.webhook_url, json=payload)
                res.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Discord trade notification failed: {e}")
            return False
