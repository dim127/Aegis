import logging
import ccxt
from typing import Optional

logger = logging.getLogger(__name__)

EXCHANGE_CONFIG = {
    "binance_futures": {
        "class": ccxt.binanceusdm,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
    },
    "bybit": {
        "class": ccxt.bybit,
        "enableRateLimit": True,
    },
    "hyperliquid": {
        "class": ccxt.hyperliquid,
        "enableRateLimit": True,
        "options": {},
    },
}


def _create_exchange(name: str = "binance_futures", api_key: str = "", api_secret: str = "",
                     wallet_address: str = "", private_key: str = ""):
    cfg = EXCHANGE_CONFIG.get(name)
    if not cfg:
        raise ValueError(f"Unknown exchange: {name}")

    exchange_params = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": cfg.get("enableRateLimit", True),
    }

    if name == "hyperliquid":
        if wallet_address:
            exchange_params["walletAddress"] = wallet_address
        if private_key:
            exchange_params["privateKey"] = private_key

    exchange = cfg["class"](exchange_params)
    if cfg.get("options"):
        exchange.options.update(cfg["options"])
    return exchange


def fetch_price(symbol: str = "BTC/USDT", exchange_name: str = "binance_futures") -> Optional[float]:
    try:
        exchange = _create_exchange(exchange_name)
        ticker = exchange.fetch_ticker(symbol)
        return ticker["last"]
    except Exception as e:
        logger.error(f"Error fetching price for {symbol} on {exchange_name}: {e}")
        return None


def place_limit_order(
    side: str,
    symbol: str,
    amount: float,
    price: float,
    exchange_name: str = "binance_futures",
    api_key: str = "",
    api_secret: str = "",
    reduce_only: bool = False,
    **kwargs,
) -> Optional[dict]:
    try:
        exchange = _create_exchange(exchange_name, api_key, api_secret)
        params = {"reduceOnly": reduce_only} if reduce_only else {}
        params.update(kwargs)
        order = exchange.create_limit_order(symbol, side, amount, price, params)
        logger.info(f"Limit {side} order placed: {amount} {symbol} @ {price}")
        return order
    except Exception as e:
        logger.error(f"Error placing limit {side} order for {symbol}: {e}")
        return None


def place_market_order(
    side: str,
    symbol: str,
    amount: float,
    exchange_name: str = "binance_futures",
    api_key: str = "",
    api_secret: str = "",
    reduce_only: bool = False,
    **kwargs,
) -> Optional[dict]:
    try:
        exchange = _create_exchange(exchange_name, api_key, api_secret)
        params = {"reduceOnly": reduce_only} if reduce_only else {}
        params.update(kwargs)
        order = exchange.create_market_order(symbol, side, amount, params)
        logger.info(f"Market {side} order filled: {amount} {symbol}")
        return order
    except Exception as e:
        logger.error(f"Error placing market {side} order for {symbol}: {e}")
        return None


def cancel_order(order_id: str, symbol: str, exchange_name: str = "binance_futures") -> bool:
    try:
        exchange = _create_exchange(exchange_name)
        exchange.cancel_order(order_id, symbol)
        logger.info(f"Cancelled order {order_id} for {symbol}")
        return True
    except Exception as e:
        logger.error(f"Error cancelling order {order_id}: {e}")
        return False


def fetch_open_orders(symbol: str, exchange_name: str = "binance_futures") -> list:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_open_orders(symbol)
    except Exception as e:
        logger.error(f"Error fetching open orders for {symbol}: {e}")
        return []


def calculate_position_size(
    capital: float,
    risk_percent: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: float = 1.0,
) -> float:
    risk_amount = capital * (risk_percent / 100.0)
    price_distance = abs(entry_price - stop_loss_price)
    if price_distance == 0:
        return 0.0
    raw_size = (risk_amount / price_distance) * leverage
    return max(raw_size, 0.0)


def fetch_hyperliquid_funding(symbol: str = "BTC/USDC:USDC") -> Optional[dict]:
    try:
        exchange = _create_exchange("hyperliquid")
        return exchange.fetch_funding_rate(symbol)
    except Exception as e:
        logger.error(f"Error fetching Hyperliquid funding for {symbol}: {e}")
        return None


def fetch_hyperliquid_ohlcv(symbol: str = "BTC/USDC:USDC", interval: str = "1h",
                            limit: int = 336, exchange_name: str = "hyperliquid") -> Optional[list]:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_ohlcv(symbol, interval, limit=limit)
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol} on {exchange_name}: {e}")
        return None


def fetch_hyperliquid_tickers(exchange_name: str = "hyperliquid") -> Optional[dict]:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_tickers()
    except Exception as e:
        logger.error(f"Error fetching Hyperliquid tickers: {e}")
        return None
