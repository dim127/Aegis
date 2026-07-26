import json
import logging
from typing import Optional

from notifications.base import BaseNotifier, NotificationLevel

logger = logging.getLogger(__name__)


class WebhookNotifier(BaseNotifier):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.webhook_url = self.config.get("webhook_url", "")
        self.webhook_token = self.config.get("webhook_token", "")
        self.retries = self.config.get("retries", 3)

    def send(self, message: str, level: NotificationLevel = NotificationLevel.INFO,
             **kwargs) -> bool:
        if not self.enabled or not self.webhook_url:
            return False
        try:
            import httpx
            payload = {
                "text": self.format_message(message, level),
                "level": level.value,
                "source": "aegis",
            }
            if self.webhook_token:
                payload["token"] = self.webhook_token
            payload.update(kwargs)

            for attempt in range(self.retries):
                try:
                    with httpx.Client(timeout=10) as client:
                        res = client.post(self.webhook_url, json=payload)
                        res.raise_for_status()
                    return True
                except Exception as e:
                    if attempt < self.retries - 1:
                        continue
                    logger.error(f"Webhook send failed after {self.retries} retries: {e}")
            return False
        except Exception as e:
            logger.error(f"Webhook notifier error: {e}")
            return False

    def send_signal(self, pair: str, score: float, direction: str,
                    price: float, reason: str = None) -> bool:
        msg = (
            f"📊 SIGNAL: {pair}\n"
            f"Direction: {direction.upper()}\n"
            f"Score: {score}/100\n"
            f"Price: ${price:.4f}\n"
        )
        if reason:
            msg += f"Setup: {reason}"
        return self.send(msg, NotificationLevel.INFO, event="signal")
