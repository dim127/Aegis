import json
import os

POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")
_TRADES = None


def _ensure_loaded():
    global _TRADES
    if _TRADES is None:
        reload()


def reload():
    global _TRADES
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {}
    _TRADES = data.get("active_trades", {})


def get_trades():
    _ensure_loaded()
    return _TRADES


def save_positions(data: dict):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    global _TRADES
    _TRADES = data.get("active_trades", {})


SMC_SYMBOLS = [
    "BTC/USDC:USDC", "ETH/USDC:USDC", "BNB/USDC:USDC",
    "SOL/USDC:USDC", "HYPE/USDC:USDC",
]
