import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import execution


class IsTestnetTests(unittest.TestCase):
    def test_false_when_flag_absent(self):
        # Both assertions must sit inside the patch. environment_name() used to
        # be called outside it, so this test read whichever mode the checked-in
        # aegis_config.json happened to be in.
        with patch("execution._load_config", return_value={"exchange": {"binance": {}}}):
            self.assertFalse(execution.is_testnet())
            self.assertEqual(execution.environment_name(), "LIVE")

    def test_true_when_flag_set(self):
        with patch("execution._load_config", return_value={"exchange": {"binance": {"testnet": True}}}):
            self.assertTrue(execution.is_testnet())
            self.assertEqual(execution.environment_name(), "TESTNET")


class SandboxModeTests(unittest.TestCase):
    def test_exchange_goes_sandbox_on_testnet(self):
        with patch("execution.trading_mode", return_value="testnet"):
            exchange = execution._create_exchange()
        fapi = exchange.urls["api"]["fapiPublic"]
        self.assertIn("testnet", fapi, f"expected testnet fapi url, got {fapi}")

    def test_exchange_stays_live_when_flag_off(self):
        execution.reset_exchange_cache()
        with patch("execution.trading_mode", return_value="live"):
            exchange = execution._create_exchange()
        fapi = exchange.urls["api"]["fapiPublic"]
        self.assertNotIn("testnet", fapi, f"expected live fapi url, got {fapi}")

    def test_sandbox_disables_the_ccxt_futures_guard(self):
        # ccxt raises NotSupported on every private futures endpoint while
        # sandbox mode is on. The URLs still route to the testnet host, so the
        # guard is opted out of rather than worked around.
        execution.reset_exchange_cache()
        with patch("execution.trading_mode", return_value="testnet"):
            exchange = execution._create_exchange()
        self.assertTrue(exchange.options.get("disableFuturesSandboxWarning"))
        self.assertIn("testnet", exchange.urls["api"]["fapiPrivate"])


class TestnetCredentialsTests(unittest.TestCase):
    def test_testnet_env_preferred_over_mainnet(self):
        with (
            patch("execution.trading_mode", return_value="testnet"),
            patch.dict(os.environ, {
                "BINANCE_API_KEY": "MAINNET_KEY",
                "BINANCE_SECRET_KEY": "MAINNET_SECRET",
                "BINANCE_TESTNET_API_KEY": "TESTNET_KEY",
                "BINANCE_TESTNET_SECRET": "TESTNET_SECRET",
            }),
        ):
            creds = execution.load_exchange_credentials()
        self.assertEqual(creds, {"api_key": "TESTNET_KEY", "api_secret": "TESTNET_SECRET"})

    def test_testnet_file_fallback(self):
        tmp = tempfile.mkdtemp()
        file = Path(tmp) / "creds.json"
        file.write_text('{"api_key": "FILE_KEY", "api_secret": "FILE_SECRET"}')
        with (
            patch("execution.trading_mode", return_value="testnet"),
            patch.object(execution, "TESTNET_CREDENTIALS_PATH", file),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("BINANCE_TESTNET_API_KEY", None)
            os.environ.pop("BINANCE_TESTNET_SECRET", None)
            creds = execution.load_exchange_credentials()
        self.assertEqual(creds, {"api_key": "FILE_KEY", "api_secret": "FILE_SECRET"})

    def test_testnet_empty_when_no_keys(self):
        with (
            patch("execution.trading_mode", return_value="testnet"),
            patch.object(execution, "TESTNET_CREDENTIALS_PATH", Path("/nonexistent/x.json")),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("BINANCE_TESTNET_API_KEY", None)
            os.environ.pop("BINANCE_TESTNET_SECRET", None)
            self.assertEqual(execution.load_exchange_credentials(), {})
            self.assertFalse(execution.has_credentials())


class DemoTradingTests(unittest.TestCase):
    """Demo Trading is a separate environment from the sandbox, not a variant.

    Binance runs testnet.binancefuture.com and demo-fapi.binance.com side by
    side. ccxt refuses to combine them, and a key issued by one does not
    authenticate against the other.
    """

    def test_mode_resolves_from_config(self):
        for mode in ("live", "testnet", "demo"):
            with patch("execution._load_config",
                       return_value={"exchange": {"binance": {"mode": mode}}}):
                self.assertEqual(execution.trading_mode(), mode)

    def test_legacy_testnet_boolean_still_honoured(self):
        with patch("execution._load_config",
                   return_value={"exchange": {"binance": {"testnet": True}}}):
            self.assertEqual(execution.trading_mode(), "testnet")

    def test_mode_takes_precedence_over_legacy_flag(self):
        with patch("execution._load_config",
                   return_value={"exchange": {"binance": {"mode": "demo", "testnet": True}}}):
            self.assertEqual(execution.trading_mode(), "demo")
            self.assertTrue(execution.is_demo())
            self.assertFalse(execution.is_testnet())

    def test_unknown_mode_falls_back_rather_than_guessing_live(self):
        with patch("execution._load_config",
                   return_value={"exchange": {"binance": {"mode": "nonsense", "testnet": True}}}):
            self.assertEqual(execution.trading_mode(), "testnet")

    def test_is_paper_covers_both_paper_environments(self):
        for mode, paper in (("live", False), ("testnet", True), ("demo", True)):
            with patch("execution.trading_mode", return_value=mode):
                self.assertEqual(execution.is_paper(), paper, mode)

    def test_demo_routes_to_the_demo_host(self):
        execution.reset_exchange_cache()
        with patch("execution.trading_mode", return_value="demo"):
            exchange = execution._create_exchange()
        self.assertIn("demo-fapi.binance.com", exchange.urls["api"]["fapiPrivate"])
        # Sandbox must stay off: ccxt raises if demo is enabled on top of it.
        self.assertFalse(exchange.isSandboxModeEnabled)

    def test_demo_never_falls_back_to_live_credentials(self):
        # The dangerous case: a paper mode silently picking up a real key.
        with (
            patch("execution.trading_mode", return_value="demo"),
            patch.object(execution, "DEMO_CREDENTIALS_PATH", Path("/nonexistent/x.json")),
            patch.dict(os.environ, {
                "BINANCE_API_KEY": "MAINNET_KEY",
                "BINANCE_SECRET_KEY": "MAINNET_SECRET",
            }),
        ):
            os.environ.pop("BINANCE_DEMO_API_KEY", None)
            os.environ.pop("BINANCE_DEMO_SECRET", None)
            self.assertEqual(execution.load_exchange_credentials(), {})

    def test_demo_does_not_read_testnet_credentials(self):
        tmp = tempfile.mkdtemp()
        testnet_file = Path(tmp) / "testnet.json"
        testnet_file.write_text('{"api_key": "TESTNET_KEY", "api_secret": "TESTNET_SECRET"}')
        with (
            patch("execution.trading_mode", return_value="demo"),
            patch.object(execution, "TESTNET_CREDENTIALS_PATH", testnet_file),
            patch.object(execution, "DEMO_CREDENTIALS_PATH", Path("/nonexistent/x.json")),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("BINANCE_DEMO_API_KEY", None)
            os.environ.pop("BINANCE_DEMO_SECRET", None)
            self.assertEqual(execution.load_exchange_credentials(), {})

    def test_demo_env_credentials_are_used(self):
        with (
            patch("execution.trading_mode", return_value="demo"),
            patch.dict(os.environ, {
                "BINANCE_DEMO_API_KEY": "DEMO_KEY",
                "BINANCE_DEMO_SECRET": "DEMO_SECRET",
                "BINANCE_API_KEY": "MAINNET_KEY",
            }),
        ):
            creds = execution.load_exchange_credentials()
        self.assertEqual(creds, {"api_key": "DEMO_KEY", "api_secret": "DEMO_SECRET"})

    def test_demo_journal_is_isolated_from_live_and_testnet(self):
        tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(tmp, "live.db")
        db.SIGNALS_DB_PATH = os.path.join(tmp, "live_signals.db")
        db.TESTNET_DB_PATH = os.path.join(tmp, "testnet.db")
        db.TESTNET_SIGNALS_PATH = os.path.join(tmp, "testnet_signals.db")
        db.DEMO_DB_PATH = os.path.join(tmp, "demo.db")
        db.DEMO_SIGNALS_PATH = os.path.join(tmp, "demo_signals.db")
        with patch("execution.trading_mode", return_value="demo"):
            self.assertEqual(db._active_paths(), (db.DEMO_DB_PATH, db.DEMO_SIGNALS_PATH))
            db.log_signal({
                "pair": "BTC/USDT:USDT", "tf_combo": "15m/1m", "direction": "long",
                "entry": 100.0, "sl": 95.0, "tp": 115.0, "rr": 3.0,
            })
            self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)
        self.assertTrue(os.path.exists(db.DEMO_DB_PATH))
        self.assertFalse(os.path.exists(db.DB_PATH))
        self.assertFalse(os.path.exists(db.TESTNET_DB_PATH))


class TestnetDbIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(self.tmp, "live_cache.db")
        db.SIGNALS_DB_PATH = os.path.join(self.tmp, "live_signals.db")
        db.TESTNET_DB_PATH = os.path.join(self.tmp, "testnet_cache.db")
        db.TESTNET_SIGNALS_PATH = os.path.join(self.tmp, "testnet_signals.db")

    def test_live_paths_when_flag_off(self):
        with patch("execution.trading_mode", return_value="live"):
            self.assertEqual(db._active_paths(), (db.DB_PATH, db.SIGNALS_DB_PATH))

    def test_testnet_paths_when_flag_set(self):
        with patch("execution.trading_mode", return_value="testnet"):
            self.assertEqual(db._active_paths(), (db.TESTNET_DB_PATH, db.TESTNET_SIGNALS_PATH))

    def test_journal_written_to_testnet_db_only(self):
        with patch("execution.trading_mode", return_value="testnet"):
            db.log_signal({
                "pair": "BTC/USDT:USDT",
                "tf_combo": "15m/1m",
                "direction": "long",
                "entry": 100.0,
                "sl": 95.0,
                "tp": 115.0,
                "rr": 3.0,
            })
            self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)
        live = db.DB_PATH
        testnet = db.TESTNET_DB_PATH
        self.assertTrue(os.path.exists(testnet), "testnet db must exist")
        self.assertFalse(os.path.exists(live), "live db must stay untouched")

    def test_live_journal_does_not_touch_testnet_db(self):
        with patch("execution.trading_mode", return_value="live"):
            db.log_signal({
                "pair": "ETH/USDT:USDT",
                "tf_combo": "1h/5m",
                "direction": "short",
                "entry": 2000.0,
                "sl": 2050.0,
                "tp": 1850.0,
                "rr": 3.0,
            })
            self.assertEqual(len(db.fetch_trade_journal("PENDING")), 1)
        self.assertFalse(os.path.exists(db.TESTNET_DB_PATH))


if __name__ == "__main__":
    unittest.main()
