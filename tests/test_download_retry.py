"""Rate-limit retry: a 429 must be retried, not treated as absence of data.

HYPE and XRP lost their most recent 9 days of history this way — the old
code caught every exception the same way, logged "failed", and moved on. The
cache then looked complete (has_cached only checks the oldest row) while
silently missing the newest data, which is exactly the region a fresh
backtest run cares about most.
"""
import unittest
from unittest.mock import patch

import ccxt

from analysis.backtest.download_history import MAX_RETRIES, _request_with_backoff


class BackoffRetryTests(unittest.TestCase):
    def test_succeeds_immediately_with_no_error(self):
        calls = []
        result = _request_with_backoff(lambda: calls.append(1) or "ok")
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_a_rate_limit_error_and_then_succeeds(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ccxt.RateLimitExceeded("429 Too Many Requests")
            return "recovered"

        with patch("time.sleep"):
            result = _request_with_backoff(flaky)
        self.assertEqual(result, "recovered")
        self.assertEqual(attempts["n"], 3)

    def test_gives_up_after_max_retries_and_raises(self):
        def always_limited():
            raise ccxt.RateLimitExceeded("429 Too Many Requests")

        with patch("time.sleep"):
            with self.assertRaises(ccxt.RateLimitExceeded):
                _request_with_backoff(always_limited)

    def test_does_not_retry_a_non_network_error(self):
        # A bad symbol or malformed request should fail fast, not spend five
        # rounds of backoff on something retrying can never fix.
        calls = {"n": 0}

        def bad_request():
            calls["n"] += 1
            raise ccxt.BadSymbol("no such market")

        with self.assertRaises(ccxt.BadSymbol):
            _request_with_backoff(bad_request)
        self.assertEqual(calls["n"], 1)

    def test_backoff_delay_grows_between_attempts(self):
        delays = []
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 4:
                raise ccxt.DDoSProtection("slow down")
            return "ok"

        with patch("time.sleep", side_effect=delays.append):
            _request_with_backoff(flaky)
        self.assertEqual(len(delays), 3)
        self.assertLess(delays[0], delays[1])
        self.assertLess(delays[1], delays[2])

    def test_max_retries_is_more_than_one(self):
        # A single retry would not have covered a burst 429 across 35
        # pair/timeframe requests in quick succession.
        self.assertGreater(MAX_RETRIES, 1)


if __name__ == "__main__":
    unittest.main()
