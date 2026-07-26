import json
import os

POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "positions.json")

_TRADES = None
_WEB_POSITIONS = None


def _ensure_loaded():
    global _TRADES, _WEB_POSITIONS
    if _TRADES is None:
        reload()


def reload():
    global _TRADES, _WEB_POSITIONS
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {}
    _TRADES = data.get("active_trades", {})
    _WEB_POSITIONS = data.get("web_positions", {})


def get_trades():
    _ensure_loaded()
    return _TRADES


def get_web_positions():
    _ensure_loaded()
    return _WEB_POSITIONS


def save_positions(data: dict):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    global _TRADES, _WEB_POSITIONS
    _TRADES = data.get("active_trades", {})
    _WEB_POSITIONS = data.get("web_positions", {})


DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]
ALTCOIN_SYMBOLS = [
    "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD", "ADA-USD",
    "AVAX-USD", "DOGE-USD", "LINK-USD", "DOT-USD",
]

SCORING_STRICT_THRESHOLD = 65
SCORING_TECH_MAX = 40
SCORING_VOL_MAX = 20
SCORING_MARKET_STRUCTURE_MAX = 20
SCORING_DERIVATIVES_MAX = 20
SCORING_SENTIMENT_MAX = 10
