"""Public market data from Hyperliquid perpetuals.

Aegis is a signal scanner: it reports SMC setups and never places an order.
Everything here is public — no API key, no credentials on disk, no way for the
process to touch an account even by accident. That is a deliberate property,
not an omission; the safest execution path is the one that does not exist.

The module keeps the name `execution` because every caller imports it that way.
"""
import json
import logging
from pathlib import Path
from typing import Optional

import ccxt

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "aegis_config.json"

EXCHANGE_CONFIG = {
    "hyperliquid": {
        "class": ccxt.hyperliquid,
        "enableRateLimit": True,
        "options": {},
    },
}


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def environment_name() -> str:
    """Aegis only reads public data, so there is a single environment."""
    return "SIGNAL-ONLY"


_EXCHANGE_CACHE: dict = {}


def _create_exchange(name: str = "hyperliquid", **kwargs):
    """Return a ccxt client, reusing one per configuration.

    Clients are cached because every helper below calls this. Building a fresh
    client per call re-fetches markets and resets ccxt's rate-limit throttle,
    which invites an IP ban at the 60-second scan cadence.
    """
    cfg = EXCHANGE_CONFIG.get(name)
    if not cfg:
        raise ValueError(f"Unknown exchange: {name}")

    cache_key = (name, tuple(sorted(kwargs.items())))
    cached = _EXCHANGE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    params = {"enableRateLimit": cfg.get("enableRateLimit", True)}
    params.update(kwargs)
    exchange = cfg["class"](params)
    if cfg.get("options"):
        exchange.options.update(cfg["options"])
    _EXCHANGE_CACHE[cache_key] = exchange
    return exchange


def reset_exchange_cache() -> None:
    """Drop cached clients (tests, or after a config change)."""
    _EXCHANGE_CACHE.clear()


def fetch_price(symbol: str = "BTC/USDC:USDC", exchange_name: str = "hyperliquid") -> Optional[float]:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_ticker(symbol)["last"]
    except Exception as e:
        logger.error(f"Error fetching price for {symbol} on {exchange_name}: {e}")
        return None


def fetch_ohlcv(symbol: str = "BTC/USDC:USDC", interval: str = "1h",
                limit: int = 336, exchange_name: str = "hyperliquid") -> Optional[list]:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_ohlcv(symbol, interval, limit=limit)
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol} on {exchange_name}: {e}")
        return None


def get_market(symbol: str, exchange_name: str = "hyperliquid") -> Optional[dict]:
    try:
        exchange = _create_exchange(exchange_name)
        if not exchange.markets:
            exchange.load_markets()
        return exchange.market(symbol)
    except Exception as e:
        logger.error(f"Error loading market {symbol}: {e}")
        return None


def quantize_price(symbol: str, price: float, exchange_name: str = "hyperliquid") -> float:
    """Snap a price to the symbol's tick size.

    A signal quoting a price that cannot exist on the book is a broken signal:
    rounding to two decimals collapsed XRP's risk distance to a single cent.
    """
    try:
        exchange = _create_exchange(exchange_name)
        if not exchange.markets:
            exchange.load_markets()
        return float(exchange.price_to_precision(symbol, price))
    except Exception as e:
        logger.error(f"Error quantizing price for {symbol}: {e}")
        return price
