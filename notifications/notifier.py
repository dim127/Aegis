"""Notification delivery: severity routing, deduplication, and isolation.

Three problems, one layer.

**Repetition.** The heartbeat runs every 15 minutes, so a setup waiting three
hours for its entry produced twelve near-identical messages. A feed that
annoying gets muted, and a muted feed collects no data — which would quietly
defeat the whole reason the heartbeat exists.

**Ambiguity.** Naive deduplication makes it worse, not better: suppress the
repeats entirely and silence once again means either "nothing changed" or "the
bot is dead". So duplicates are suppressed only up to `keepalive_s`, after which
one goes out regardless. Quiet, but never silent.

**Coupling.** Delivery must never take the scanner down with it. Telegram being
unreachable is an observability failure, not a reason to stop producing signals,
so every send is isolated and reported by return value rather than exception.
"""
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class Severity(IntEnum):
    DEBUG = 10
    INFO = 20
    SIGNAL = 30      # a setup, or a heartbeat
    WARNING = 40     # degraded but running
    CRITICAL = 50    # needs attention now


# Below this, nothing reaches the chat — it only goes to the log.
CHAT_THRESHOLD = Severity.SIGNAL


@dataclass(frozen=True)
class Notification:
    text: str
    severity: Severity = Severity.SIGNAL
    # Two notifications sharing a key are the same event restated. None means
    # "always deliver".
    dedupe_key: Optional[str] = None


class Notifier(Protocol):
    async def send(self, msg: Notification) -> bool: ...


class NullNotifier:
    """Records instead of sending. Lets the suite run with zero network calls."""

    def __init__(self):
        self.sent: list[Notification] = []

    async def send(self, msg: Notification) -> bool:
        self.sent.append(msg)
        return True


@dataclass
class LogOnlyNotifier:
    """Drops everything below CHAT_THRESHOLD into the log."""

    inner: Notifier
    threshold: Severity = CHAT_THRESHOLD

    async def send(self, msg: Notification) -> bool:
        if msg.severity < self.threshold:
            logger.info(f"[{msg.severity.name}] {msg.text}")
            return True
        return await self.inner.send(msg)


@dataclass
class DedupeNotifier:
    """Send a given key at most once per `min_interval_s`.

    One parameter, deliberately. A first attempt had separate ttl_s and
    keepalive_s, and they collapsed into each other: a message went out every
    min(ttl, keepalive), so the second knob did nothing but obscure the first.

    The single interval already gives both behaviours. A state that keeps
    changing produces new keys and delivers immediately; a state that does not
    change is restated once per interval — quiet, but never silent, so the
    absence of messages still never has to be interpreted.

    It must exceed the heartbeat period to suppress anything at all. At 15-minute
    heartbeats and a 15-minute interval, every repeat arrives exactly as the
    previous one expires and nothing is ever suppressed.
    """

    inner: Notifier
    min_interval_s: int = 3600
    _seen: dict = field(default_factory=dict)
    _last_sent: float = field(default=0.0)

    def _now(self) -> float:
        return time.monotonic()

    def should_send(self, msg: Notification) -> tuple[bool, str]:
        """Pure decision, separated so the policy is testable without a bot."""
        # CRITICAL is never suppressed. An outage restating itself is exactly
        # the case where repetition is the point.
        if msg.severity >= Severity.CRITICAL:
            return True, "critical"
        if msg.dedupe_key is None:
            return True, "no_key"

        seen_at = self._seen.get(msg.dedupe_key)
        if seen_at is None:
            return True, "new"
        if self._now() - seen_at >= self.min_interval_s:
            return True, "interval_elapsed"
        return False, "duplicate"

    async def send(self, msg: Notification) -> bool:
        allowed, _ = self.should_send(msg)
        if not allowed:
            logger.debug(f"suppressed duplicate: {msg.dedupe_key}")
            return False

        delivered = await self.inner.send(msg)
        if delivered:
            now = self._now()
            # Only remember what actually got through. Recording a failed send
            # would suppress the next attempt that might have succeeded.
            self._seen = {k: v for k, v in self._seen.items()
                          if now - v < self.min_interval_s * 2}
            if msg.dedupe_key is not None:
                self._seen[msg.dedupe_key] = now
            self._last_sent = now
        return delivered


@dataclass
class TelegramNotifier:
    """Delivers to one chat, and swallows its own failures by design.

    Returns False rather than raising: the caller is a scan loop, and a
    scanner that stops producing signals because a message failed to send has
    confused its output channel for its purpose.
    """

    bot: object
    chat_id: object
    parse_mode: str = "Markdown"

    async def send(self, msg: Notification) -> bool:
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, text=msg.text, parse_mode=self.parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Telegram send failed ({msg.severity.name}): {e}")
            return False


def build_notifier(bot, chat_id, min_interval_s: int = 3600) -> Notifier:
    """Standard stack: severity filter -> dedupe -> Telegram."""
    return LogOnlyNotifier(
        DedupeNotifier(TelegramNotifier(bot, chat_id), min_interval_s=min_interval_s)
    )


def setup_key(setup: dict) -> str:
    """Identity of a setup, so restating it is recognisable as a repeat.

    Keyed on the FVG that triggered it rather than the entry price: the entry is
    a gap midpoint that drifts every scan, which is what let one setup announce
    itself six times in forty minutes.
    """
    return "|".join(str(setup.get(k, "")) for k in
                    ("pair", "tf_combo", "direction", "fvg_timestamp"))


def heartbeat_key(report: dict) -> str:
    """Identity of a heartbeat, derived from the state it describes.

    Two heartbeats listing the same signals in the same states say the same
    thing, however many minutes apart.
    """
    parts = []
    for bucket in ("valid", "invalid"):
        for s in report.get(bucket) or []:
            parts.append(f"{s.get('pair')}:{s.get('tf_combo')}:{s.get('status')}")
    return "heartbeat|" + ",".join(sorted(parts))
