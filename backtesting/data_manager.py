import os
import logging
from typing import Optional, List
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "ohlcv")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _yf_symbol(symbol: str) -> str:
    s = symbol.replace("/", "-").split(":")[0]
    if not s.endswith("-USD") and not s.endswith("-USDT"):
        s = f"{s}-USD"
    return s


def _filename(symbol: str, interval: str) -> str:
    safe = symbol.replace("/", "_").replace("-", "_").replace(":", "_")
    return os.path.join(DATA_DIR, f"{safe}_{interval}.parquet")


def download_data(
    symbol: str,
    interval: str = "1h",
    days: int = 180,
    force: bool = False,
) -> pd.DataFrame:
    ensure_data_dir()
    fpath = _filename(symbol, interval)

    if not force and os.path.exists(fpath):
        try:
            df = pd.read_parquet(fpath)
            last_time = df.index[-1]
            age = datetime.utcnow() - last_time
            if age < timedelta(hours=6):
                logger.info(f"  Using cached data for {symbol} ({interval})")
                return df
        except Exception as e:
            logger.warning(f"  Cache read failed for {symbol}: {e}")

    logger.info(f"  Downloading {symbol} ({interval}, {days}d)")
    yf_sym = _yf_symbol(symbol)
    period = f"{days}d"
    ticker = yf.Ticker(yf_sym)
    df = ticker.history(period=period, interval=interval)

    if df.empty:
        raise ValueError(f"No data for {symbol}")

    df.columns = [c.capitalize() for c in df.columns]

    try:
        df.to_parquet(fpath)
        logger.info(f"  Cached to {fpath}")
    except Exception as e:
        logger.warning(f"  Failed to cache data: {e}")

    return df


def download_multiple(
    symbols: List[str],
    interval: str = "1h",
    days: int = 180,
    force: bool = False,
) -> dict[str, pd.DataFrame]:
    results = {}
    for sym in symbols:
        try:
            results[sym] = download_data(sym, interval, days, force)
        except Exception as e:
            logger.error(f"Failed to download {sym}: {e}")
    return results


def list_cached_data() -> pd.DataFrame:
    ensure_data_dir()
    files = os.listdir(DATA_DIR) if os.path.exists(DATA_DIR) else []
    rows = []
    for fname in files:
        if not fname.endswith(".parquet"):
            continue
        parts = fname.replace(".parquet", "").split("_")
        symbol = parts[0] if parts else ""
        interval = parts[-1] if len(parts) > 1 else ""
        fpath = os.path.join(DATA_DIR, fname)
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
        size = os.path.getsize(fpath)
        rows.append({"symbol": symbol, "interval": interval, "cached_at": mtime, "size_kb": round(size / 1024, 1)})
    return pd.DataFrame(rows)


def clear_cache(symbol: str = None, interval: str = None):
    ensure_data_dir()
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".parquet"):
            continue
        if symbol and symbol.replace("/", "_") not in fname:
            continue
        if interval and interval not in fname:
            continue
        os.remove(os.path.join(DATA_DIR, fname))
        logger.info(f"Cleared cache: {fname}")
