import json
import logging
import os
from pathlib import Path
from typing import Optional

import ccxt
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "aegis_config.json"
CREDENTIALS_PATH = Path(__file__).resolve().parent / "binance_credentials.json"
TESTNET_CREDENTIALS_PATH = Path(__file__).resolve().parent / "binance_testnet_credentials.json"
DEMO_CREDENTIALS_PATH = Path(__file__).resolve().parent / "binance_demo_credentials.json"

EXCHANGE_CONFIG = {
    "binance_futures": {
        "class": ccxt.binanceusdm,
        "enableRateLimit": True,
        "options": {"defaultType": "future"},
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


TRADING_MODES = ("live", "testnet", "demo")


def trading_mode() -> str:
    """Which environment to trade against: live, testnet, or demo.

    Binance runs two separate paper environments and they are not
    interchangeable:

    * testnet  -> testnet.binancefuture.com, keys from testnet.binancefuture.com
    * demo     -> demo-fapi.binance.com, keys from demo.binance.com

    ccxt refuses to combine them (enable_demo_trading raises when sandbox mode
    is on), and a key issued by one environment is meaningless to the other.
    Reads exchange.binance.mode, falling back to the legacy boolean
    exchange.binance.testnet.
    """
    binance = _load_config().get("exchange", {}).get("binance", {})
    mode = str(binance.get("mode", "")).strip().lower()
    if mode in TRADING_MODES:
        return mode
    if mode:
        logger.warning(f"Unknown exchange.binance.mode '{mode}', falling back")
    return "testnet" if binance.get("testnet", False) else "live"


def is_testnet() -> bool:
    """True only for the sandbox environment (testnet.binancefuture.com)."""
    return trading_mode() == "testnet"


def is_demo() -> bool:
    """True only for Binance Demo Trading (demo-fapi.binance.com)."""
    return trading_mode() == "demo"


def is_paper() -> bool:
    """True when no real money is at stake. Drives DB isolation and guards."""
    return trading_mode() != "live"


def environment_name() -> str:
    return trading_mode().upper()


def load_exchange_credentials() -> dict:
    """Read Binance API credentials (empty dict when unset).

    Testnet mode: .env BINANCE_TESTNET_API_KEY/BINANCE_TESTNET_SECRET >
    binance_testnet_credentials.json.
    Live mode: .env BINANCE_API_KEY/BINANCE_SECRET_KEY >
    binance_credentials.json > aegis_config.json exchange.binance.
    """
    load_dotenv()
    mode = trading_mode()
    if mode != "live":
        # Never fall through to live credentials: a paper mode with a real key
        # silently pointed at the wrong host is how real money gets spent.
        if mode == "demo":
            env_names = ("BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET")
            path = DEMO_CREDENTIALS_PATH
        else:
            env_names = ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET")
            path = TESTNET_CREDENTIALS_PATH
        env_key = os.getenv(env_names[0], "").strip()
        env_secret = os.getenv(env_names[1], "").strip()
        if env_key and env_secret:
            return {"api_key": env_key, "api_secret": env_secret}
        if path.exists():
            try:
                with path.open() as f:
                    creds = json.load(f)
                if creds.get("api_key") and creds.get("api_secret"):
                    return creds
            except (OSError, json.JSONDecodeError):
                pass
        return {}
    env_key = os.getenv("BINANCE_API_KEY", "").strip()
    env_secret = os.getenv("BINANCE_SECRET_KEY", "").strip()
    if env_key and env_secret:
        return {"api_key": env_key, "api_secret": env_secret}
    if CREDENTIALS_PATH.exists():
        try:
            with CREDENTIALS_PATH.open() as f:
                creds = json.load(f)
            if creds.get("api_key") and creds.get("api_secret"):
                return creds
        except (OSError, json.JSONDecodeError):
            pass
    return _load_config().get("exchange", {}).get("binance", {})


_EXCHANGE_CACHE: dict = {}


def _create_exchange(
    name: str = "binance_futures",
    api_key: str = "",
    api_secret: str = "",
    **kwargs,
):
    """Return a ccxt client, reusing one per (exchange, credentials, network).

    Clients are cached because every network helper below calls this. Building a
    fresh client per call re-reads credentials from disk, re-fetches markets and
    resets ccxt's rate-limit throttle state, which invites an IP ban at the
    60-second scan cadence.
    """
    cfg = EXCHANGE_CONFIG.get(name)
    if not cfg:
        raise ValueError(f"Unknown exchange: {name}")

    creds = load_exchange_credentials()
    key = api_key or creds.get("api_key", "")
    secret = api_secret or creds.get("api_secret", "")
    mode = trading_mode()

    cache_key = (name, key, mode, tuple(sorted(kwargs.items())))
    cached = _EXCHANGE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    exchange_params = {
        "apiKey": key,
        "secret": secret,
        "enableRateLimit": cfg.get("enableRateLimit", True),
    }
    exchange_params.update(kwargs)
    exchange = cfg["class"](exchange_params)
    if cfg.get("options"):
        exchange.options.update(cfg["options"])
    if mode == "testnet":
        exchange.set_sandbox_mode(True)
        # ccxt raises NotSupported on every *private* futures endpoint while
        # sandbox mode is on (binance.py: the fapiPrivate branch), because
        # Binance deprecated the futures testnet in favour of demo trading.
        # Public endpoints are unaffected, which is why prices worked while
        # fetch_balance and fetch_positions did not. The URLs still route to
        # testnet.binancefuture.com and the endpoints still respond, so this
        # opts out of the guard rather than working around it.
        exchange.options["disableFuturesSandboxWarning"] = True
        logger.info("Exchange in TESTNET mode (testnet.binancefuture.com)")
    elif mode == "demo":
        # Demo Trading is a different environment from the sandbox, not a
        # variant of it — ccxt raises if sandbox mode is already on. Keys come
        # from demo.binance.com/en/my/settings/api-management and a testnet key
        # will not authenticate here.
        exchange.enable_demo_trading(True)
        logger.info("Exchange in DEMO mode (demo-fapi.binance.com)")
    _EXCHANGE_CACHE[cache_key] = exchange
    return exchange


def reset_exchange_cache() -> None:
    """Drop cached clients (call after credentials or the testnet flag change)."""
    _EXCHANGE_CACHE.clear()


def has_credentials(exchange_name: str = "binance_futures") -> bool:
    creds = load_exchange_credentials()
    return bool(creds.get("api_key") and creds.get("api_secret"))


def fetch_price(symbol: str = "BTC/USDT:USDT", exchange_name: str = "binance_futures") -> Optional[float]:
    try:
        exchange = _create_exchange(exchange_name)
        ticker = exchange.fetch_ticker(symbol)
        return ticker["last"]
    except Exception as e:
        logger.error(f"Error fetching price for {symbol} on {exchange_name}: {e}")
        return None


def fetch_ohlcv(symbol: str = "BTC/USDT:USDT", interval: str = "1h",
                limit: int = 336, exchange_name: str = "binance_futures") -> Optional[list]:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_ohlcv(symbol, interval, limit=limit)
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol} on {exchange_name}: {e}")
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


def place_stop_orders(
    symbol: str,
    amount: float,
    direction: str,
    sl: float,
    tp: float,
    exchange_name: str = "binance_futures",
    api_key: str = "",
    api_secret: str = "",
) -> tuple[Optional[dict], Optional[dict]]:
    """Attach SL and TP market-stop orders (reduce-only) after entry fills."""
    close_side = "sell" if direction == "long" else "buy"
    sl_order = tp_order = None
    try:
        exchange = _create_exchange(exchange_name, api_key, api_secret)
        sl_order = exchange.create_order(
            symbol, "STOP_MARKET", close_side, amount, None,
            params={"stopPrice": sl, "reduceOnly": True},
        )
        logger.info(f"SL order placed: {amount} {symbol} @ {sl}")
        tp_order = exchange.create_order(
            symbol, "TAKE_PROFIT_MARKET", close_side, amount, None,
            params={"stopPrice": tp, "reduceOnly": True},
        )
        logger.info(f"TP order placed: {amount} {symbol} @ {tp}")
    except Exception as e:
        logger.error(f"Error placing SL/TP for {symbol}: {e}")
    return sl_order, tp_order


def cancel_order(order_id: str, symbol: str, exchange_name: str = "binance_futures") -> bool:
    try:
        exchange = _create_exchange(exchange_name)
        exchange.cancel_order(order_id, symbol)
        logger.info(f"Cancelled order {order_id} for {symbol}")
        return True
    except Exception as e:
        logger.error(f"Error cancelling order {order_id}: {e}")
        return False


def fetch_order(order_id: str, symbol: str, exchange_name: str = "binance_futures") -> Optional[dict]:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_order(order_id, symbol)
    except Exception as e:
        logger.error(f"Error fetching order {order_id} for {symbol}: {e}")
        return None


def fetch_open_orders(symbol: str, exchange_name: str = "binance_futures") -> list:
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_open_orders(symbol)
    except Exception as e:
        logger.error(f"Error fetching open orders for {symbol}: {e}")
        return []


def fetch_positions(exchange_name: str = "binance_futures") -> Optional[list]:
    """Open positions, or None when the call failed.

    None and [] mean different things to the caller: [] is "flat", None is "we
    do not know". Returning [] on error would let monitor_open mark a live
    position CLOSED on a single API hiccup.
    """
    try:
        exchange = _create_exchange(exchange_name)
        return exchange.fetch_positions()
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return None


def fetch_equity(exchange_name: str = "binance_futures") -> Optional[float]:
    """Free + used USDT balance, or None when unavailable."""
    try:
        exchange = _create_exchange(exchange_name)
        balance = exchange.fetch_balance()
        total = balance.get("total", {}).get("USDT")
        return float(total) if total is not None else None
    except Exception as e:
        logger.error(f"Error fetching balance: {e}")
        return None


def get_market(symbol: str, exchange_name: str = "binance_futures") -> Optional[dict]:
    try:
        exchange = _create_exchange(exchange_name)
        if not exchange.markets:
            exchange.load_markets()
        return exchange.market(symbol)
    except Exception as e:
        logger.error(f"Error loading market {symbol}: {e}")
        return None


def quantize_price(symbol: str, price: float, exchange_name: str = "binance_futures") -> float:
    """Snap a price to the symbol's tick size (falls back to the raw price)."""
    try:
        exchange = _create_exchange(exchange_name)
        if not exchange.markets:
            exchange.load_markets()
        return float(exchange.price_to_precision(symbol, price))
    except Exception as e:
        logger.error(f"Error quantizing price for {symbol}: {e}")
        return price


def quantize_amount(symbol: str, amount: float, exchange_name: str = "binance_futures") -> float:
    """Snap an order size to the symbol's step size (falls back to the raw size)."""
    try:
        exchange = _create_exchange(exchange_name)
        if not exchange.markets:
            exchange.load_markets()
        return float(exchange.amount_to_precision(symbol, amount))
    except Exception as e:
        logger.error(f"Error quantizing amount for {symbol}: {e}")
        return amount


def calculate_position_size(
    capital: float,
    risk_percent: float,
    entry_price: float,
    stop_loss_price: float,
    max_notional_pct: float = 300.0,
) -> float:
    """Size a position so a stop-out loses exactly risk_percent of capital.

    Leverage is deliberately not a factor: it changes the margin posted, not the
    loss taken when the stop is hit. Multiplying size by leverage would multiply
    risk instead.

    The notional clamp is a backstop against a degenerate stop distance (a
    tick-rounded stop can make price_distance almost zero and the raw size
    enormous); max_notional_pct is a percentage of capital.
    """
    price_distance = abs(entry_price - stop_loss_price)
    if price_distance <= 0 or entry_price <= 0 or capital <= 0:
        return 0.0

    risk_amount = capital * (risk_percent / 100.0)
    raw_size = risk_amount / price_distance

    max_notional = capital * (max_notional_pct / 100.0)
    if raw_size * entry_price > max_notional:
        capped = max_notional / entry_price
        logger.warning(
            f"Position size capped by notional limit: {raw_size:.6f} -> {capped:.6f} "
            f"(stop distance {price_distance / entry_price * 100:.3f}% of price)"
        )
        raw_size = capped

    return max(raw_size, 0.0)


def meets_exchange_minimums(
    symbol: str, amount: float, price: float, exchange_name: str = "binance_futures"
) -> bool:
    """False when the order is below the symbol's min quantity or min notional."""
    market = get_market(symbol, exchange_name)
    if market is None:
        return True  # cannot verify; let the exchange reject it
    limits = market.get("limits") or {}
    min_amount = (limits.get("amount") or {}).get("min")
    min_cost = (limits.get("cost") or {}).get("min")
    if min_amount is not None and amount < float(min_amount):
        logger.warning(f"{symbol}: amount {amount} below minimum {min_amount}")
        return False
    if min_cost is not None and amount * price < float(min_cost):
        logger.warning(
            f"{symbol}: notional {amount * price:.2f} below minimum {min_cost}"
        )
        return False
    return True


def configure_symbol(
    symbol: str,
    leverage: int = 1,
    margin_mode: str = "isolated",
    exchange_name: str = "binance_futures",
) -> bool:
    """Set leverage and margin mode so the account default does not silently apply."""
    try:
        exchange = _create_exchange(exchange_name)
        try:
            exchange.set_margin_mode(margin_mode, symbol)
        except Exception as e:
            # Binance errors when the mode is already what we asked for.
            logger.debug(f"{symbol}: margin mode unchanged ({e})")
        exchange.set_leverage(leverage, symbol)
        logger.info(f"{symbol}: leverage {leverage}x, margin {margin_mode}")
        return True
    except Exception as e:
        logger.error(f"Error configuring {symbol}: {e}")
        return False
