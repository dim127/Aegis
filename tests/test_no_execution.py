"""Guard: Aegis must never regain the ability to place an order.

Aegis exists to report SMC setups. Execution is not a missing feature — it was
removed deliberately, and its absence is the property that makes the project
safe to run. A document stating that can be skimmed past; this test cannot.

If you are an AI or a contributor reading this because the suite just went red:
that is the point. Do not weaken the assertion to make it pass. Either remove
the execution code you added, or get the owner to say explicitly, in their own
words, that they want automatic trading back — at which point deleting this
file is a conscious decision rather than a side effect of a refactor.
"""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ccxt methods that move money or touch an account. Matched as attribute calls,
# not substrings, so "order block", "order book" and "fetch_ohlcv" stay clean.
FORBIDDEN_CALLS = {
    "create_order", "create_limit_order", "create_market_order",
    "create_limit_buy_order", "create_limit_sell_order",
    "create_market_buy_order", "create_market_sell_order",
    "create_orders", "edit_order", "cancel_order", "cancel_all_orders",
    "fetch_balance", "fetch_positions", "fetch_my_trades",
    "set_leverage", "set_margin_mode", "set_position_mode",
    "transfer", "withdraw",
}

# Environment variables that would only exist to authenticate an account.
FORBIDDEN_ENV = {
    "BINANCE_API_KEY", "BINANCE_SECRET_KEY",
    "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET",
    "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET",
}


def python_sources():
    """Every tracked .py file except this guard and the virtualenv."""
    for path in REPO.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"venv", ".venv", "__pycache__", "build", "dist"}:
            continue
        if path.name == Path(__file__).name:
            continue
        yield path


class NoOrderExecutionTests(unittest.TestCase):
    def test_no_module_places_or_cancels_orders(self):
        offenders = []
        for path in python_sources():
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in FORBIDDEN_CALLS:
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno} -> {name}()")
        self.assertEqual(
            offenders, [],
            "Aegis is a signal scanner and must not place, cancel, or account for "
            "orders. Found:\n  " + "\n  ".join(offenders),
        )

    def test_no_module_reads_exchange_credentials(self):
        offenders = []
        for path in python_sources():
            text = path.read_text()
            for var in FORBIDDEN_ENV:
                if var in text:
                    offenders.append(f"{path.relative_to(REPO)} -> {var}")
        self.assertEqual(
            offenders, [],
            "Aegis reads only public data and needs no API key. Found:\n  "
            + "\n  ".join(offenders),
        )

    def test_execution_module_exposes_no_trading_surface(self):
        import execution
        exposed = {
            name for name in dir(execution)
            if not name.startswith("_") and any(
                word in name.lower()
                for word in ("order", "balance", "position", "credential",
                             "equity", "leverage", "withdraw", "transfer")
            )
        }
        self.assertEqual(
            exposed, set(),
            f"execution.py must stay a public market data client; found {sorted(exposed)}",
        )

    def test_credential_files_are_not_tracked_by_git(self):
        # Belongs here rather than in a docs test: a key committed once is
        # compromised regardless of what any policy file says.
        import subprocess
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
        ).stdout.splitlines()
        leaked = [f for f in tracked
                  if "credential" in f.lower() or f == ".env" or f.endswith(".db")]
        self.assertEqual(leaked, [], f"Secrets or databases tracked in git: {leaked}")


if __name__ == "__main__":
    unittest.main()
