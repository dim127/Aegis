"""Notification policy: suppress repetition without ever going silent.

The tension this layer resolves: the heartbeat repeats on purpose, so that
silence is never ambiguous, while deduplication exists to stop it repeating.
Both matter, so a repeated key is restated once per min_interval_s: quiet,
but never silent.
"""
import asyncio
import unittest

from notifications.notifier import (
    DedupeNotifier,
    LogOnlyNotifier,
    Notification,
    NullNotifier,
    Severity,
    TelegramNotifier,
    heartbeat_key,
    setup_key,
)


def run(coro):
    return asyncio.run(coro)


class Clock:
    """Controllable monotonic clock — real sleeps have no place in a test."""

    def __init__(self):
        self.t = 1000.0

    def advance(self, seconds):
        self.t += seconds


def dedupe_with_clock(inner, **kw):
    clock = Clock()
    d = DedupeNotifier(inner, **kw)
    d._now = lambda: clock.t
    return d, clock


class DeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.inner = NullNotifier()
        self.dedupe, self.clock = dedupe_with_clock(self.inner, min_interval_s=3600)

    def _signal(self, key="BTC|15m/1m|long|t1"):
        return Notification("setup", Severity.SIGNAL, dedupe_key=key)

    def test_first_message_is_delivered(self):
        self.assertTrue(run(self.dedupe.send(self._signal())))
        self.assertEqual(len(self.inner.sent), 1)

    def test_repeat_within_the_interval_is_suppressed(self):
        run(self.dedupe.send(self._signal()))
        self.clock.advance(300)
        self.assertFalse(run(self.dedupe.send(self._signal())))
        self.assertEqual(len(self.inner.sent), 1)

    def test_five_repeats_in_a_minute_send_once(self):
        for _ in range(5):
            self.clock.advance(12)
            run(self.dedupe.send(self._signal()))
        self.assertEqual(len(self.inner.sent), 1)

    def test_repeat_after_the_interval_is_delivered_again(self):
        run(self.dedupe.send(self._signal()))
        self.clock.advance(3601)
        self.assertTrue(run(self.dedupe.send(self._signal())))
        self.assertEqual(len(self.inner.sent), 2)

    def test_a_different_key_is_never_suppressed(self):
        run(self.dedupe.send(self._signal("BTC|15m/1m|long|t1")))
        self.assertTrue(run(self.dedupe.send(self._signal("ETH|1h/5m|short|t2"))))
        self.assertEqual(len(self.inner.sent), 2)

    def test_missing_key_always_delivers(self):
        msg = Notification("ad hoc", Severity.SIGNAL, dedupe_key=None)
        run(self.dedupe.send(msg))
        run(self.dedupe.send(msg))
        self.assertEqual(len(self.inner.sent), 2)


class SilenceIsNeverAmbiguousTests(unittest.TestCase):
    """The property that makes dedup safe to apply to a heartbeat."""

    def setUp(self):
        self.inner = NullNotifier()
        self.dedupe, self.clock = dedupe_with_clock(self.inner, min_interval_s=3600)

    def test_an_unchanging_state_still_reports_once_per_interval(self):
        msg = Notification("heartbeat", Severity.SIGNAL, dedupe_key="hb|same")
        run(self.dedupe.send(msg))
        # A setup can sit unfilled for hours; the state never changes. Within
        # the interval every repeat is suppressed...
        for _ in range(3):
            self.clock.advance(900)
            run(self.dedupe.send(msg))
        self.assertEqual(len(self.inner.sent), 1)
        # ...and once it elapses, one goes out so silence stays meaningful.
        self.clock.advance(900)
        run(self.dedupe.send(msg))
        self.assertEqual(len(self.inner.sent), 2)

    def test_quiet_but_not_silent_over_a_long_wait(self):
        msg = Notification("heartbeat", Severity.SIGNAL, dedupe_key="hb|same")
        sends = 0
        for _ in range(48):           # 12 hours at 15-minute intervals
            if run(self.dedupe.send(msg)):
                sends += 1
            self.clock.advance(900)
        # 48 heartbeats over 12 hours collapse to roughly one per hour.
        self.assertLessEqual(sends, 13, "must suppress the bulk of the repeats")
        self.assertGreaterEqual(sends, 10, "must not fall silent for 12 hours")


class SeverityTests(unittest.TestCase):
    def test_critical_is_never_deduped(self):
        inner = NullNotifier()
        dedupe, clock = dedupe_with_clock(inner, min_interval_s=3600)
        msg = Notification("exchange unreachable", Severity.CRITICAL, dedupe_key="same")
        for _ in range(3):
            clock.advance(1)
            run(dedupe.send(msg))
        self.assertEqual(len(inner.sent), 3)

    def test_below_threshold_never_reaches_the_chat(self):
        inner = NullNotifier()
        stack = LogOnlyNotifier(inner)
        run(stack.send(Notification("debug detail", Severity.DEBUG)))
        run(stack.send(Notification("routine", Severity.INFO)))
        self.assertEqual(inner.sent, [])

    def test_signal_and_above_reach_the_chat(self):
        inner = NullNotifier()
        stack = LogOnlyNotifier(inner)
        for sev in (Severity.SIGNAL, Severity.WARNING, Severity.CRITICAL):
            run(stack.send(Notification("x", sev)))
        self.assertEqual(len(inner.sent), 3)


class FailureIsolationTests(unittest.TestCase):
    """A dead channel must not stop the scanner."""

    def test_send_failure_is_reported_not_raised(self):
        class DeadBot:
            async def send_message(self, **kw):
                raise RuntimeError("HTTP 500")

        notifier = TelegramNotifier(DeadBot(), chat_id=1)
        self.assertFalse(run(notifier.send(Notification("x", Severity.SIGNAL))))

    def test_a_failed_send_does_not_start_the_keepalive_clock(self):
        # Otherwise an outage would look like "recently delivered" and suppress
        # the first message that could actually get through.
        class DeadBot:
            async def send_message(self, **kw):
                raise RuntimeError("down")

        dedupe, clock = dedupe_with_clock(TelegramNotifier(DeadBot(), 1), min_interval_s=3600)
        run(dedupe.send(Notification("x", Severity.SIGNAL, dedupe_key="k")))
        self.assertEqual(dedupe._last_sent, 0.0)


class KeyTests(unittest.TestCase):
    def test_setup_key_ignores_entry_price_drift(self):
        base = {"pair": "BTC/USDT:USDT", "tf_combo": "15m/1m",
                "direction": "long", "fvg_timestamp": "2026-01-01T10:00"}
        drifted = {**base, "entry": 64730.0}
        self.assertEqual(setup_key(base), setup_key({**drifted, "entry": 64700.0}))

    def test_setup_key_separates_different_fvgs(self):
        a = {"pair": "BTC/USDT:USDT", "tf_combo": "15m/1m",
             "direction": "long", "fvg_timestamp": "2026-01-01T10:00"}
        b = {**a, "fvg_timestamp": "2026-01-01T11:00"}
        self.assertNotEqual(setup_key(a), setup_key(b))

    def test_heartbeat_key_is_stable_for_an_unchanged_state(self):
        report = {"valid": [{"pair": "BTC/USDT:USDT", "tf_combo": "15m/1m",
                             "status": "PENDING"}], "invalid": []}
        self.assertEqual(heartbeat_key(report), heartbeat_key(dict(report)))

    def test_heartbeat_key_changes_when_a_signal_advances(self):
        pending = {"valid": [{"pair": "BTC/USDT:USDT", "tf_combo": "15m/1m",
                              "status": "PENDING"}], "invalid": []}
        triggered = {"valid": [{"pair": "BTC/USDT:USDT", "tf_combo": "15m/1m",
                                "status": "TRIGGERED"}], "invalid": []}
        self.assertNotEqual(heartbeat_key(pending), heartbeat_key(triggered))

    def test_heartbeat_key_ignores_ordering(self):
        a = {"valid": [{"pair": "A", "tf_combo": "1h/5m", "status": "PENDING"},
                       {"pair": "B", "tf_combo": "1h/5m", "status": "PENDING"}],
             "invalid": []}
        b = {"valid": list(reversed(a["valid"])), "invalid": []}
        self.assertEqual(heartbeat_key(a), heartbeat_key(b))


if __name__ == "__main__":
    unittest.main()
