"""Download historical OHLCV from Binance USDT-M futures to the SQLite cache.

Usage:
    ./venv/bin/python3 analysis/backtest/download_history.py --days 30
    ./venv/bin/python3 analysis/backtest/download_history.py --tfs 15m,1m
    ./venv/bin/python3 analysis/backtest/download_history.py --force
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

import ccxt
import pandas as pd

import db
from strategy.aegis_strategy import AegisSMCStrategy

TFS = ("1m", "5m", "15m", "1h", "4h")

# A run across 7 pairs x 5 timeframes makes ~35+ paginated request bursts in
# short order. Hyperliquid's 429 was previously treated as a hard failure —
# the pair/tf was skipped and its cache silently went stale (HYPE and XRP both
# missed their last 9 days this way, with no error surfaced beyond a log line
# scrolling past). ccxt raises RateLimitExceeded (a NetworkError) for a 429, so
# it is retried with exponential backoff instead of abandoned.
MAX_RETRIES = 5
BASE_BACKOFF_S = 2.0


def _request_with_backoff(fn, *args, **kwargs):
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except ccxt.NetworkError as exc:
            if attempt == MAX_RETRIES - 1:
                raise
            delay = BASE_BACKOFF_S * (2 ** attempt)
            print(f"    rate limited ({exc}), retry {attempt + 1}/{MAX_RETRIES} in {delay:.0f}s")
            time.sleep(delay)


def fetch_window(exchange, symbol: str, tf: str, since_ms: int, until_ms: int) -> list:
    candles = []
    cursor = since_ms
    while cursor < until_ms:
        batch = _request_with_backoff(exchange.fetch_ohlcv, symbol, tf, since=cursor, limit=1500)
        if not batch:
            break
        candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        time.sleep(0.25)
    return [c for c in candles if since_ms <= c[0] < until_ms]


def download_pair(strategy, symbol: str, tfs, days: int, force: bool) -> None:
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    until_ms = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp() * 1000)
    exchange = ccxt.hyperliquid({"enableRateLimit": True, "timeout": 30000})
    for tf in tfs:
        if not force and has_cached(symbol, tf, days):
            print(f"  {symbol} {tf}: cached, skipping")
            continue
        try:
            candles = fetch_window(exchange, symbol, tf, since_ms, until_ms)
        except Exception as exc:
            # Exhausted retries or a non-network failure. Raising here — rather
            # than the previous log-and-continue — would stop the whole run
            # over one pair, so this still degrades gracefully, but the
            # message now says plainly that the cache is left stale rather
            # than reading like routine progress output.
            print(f"  {symbol} {tf}: FAILED after retries, cache left stale ({exc})")
            continue
        if not candles:
            print(f"  {symbol} {tf}: no data")
            continue
        df = pd.DataFrame(candles, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df = df[~df.index.duplicated(keep="last")]
        db.save_ohlcv(symbol, tf, df)
        print(f"  {symbol} {tf}: {len(df)} candles saved")


def has_cached(symbol: str, tf: str, days: int) -> bool:
    df = db.get_cached_ohlcv(symbol, tf, max_age_minutes=days * 24 * 60)
    if df is None or len(df) < 500:
        return False
    oldest = pd.to_datetime(df.index[0], utc=True)
    return (pd.Timestamp.now(tz="UTC") - oldest) >= pd.Timedelta(days=days - 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download historical OHLCV to the local cache.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--tfs", default=",".join(TFS), help="comma separated timeframes")
    parser.add_argument("--pairs", default="", help="comma separated symbols (default: config pairs)")
    parser.add_argument("--force", action="store_true", help="re-download everything")
    args = parser.parse_args()

    strategy = AegisSMCStrategy()
    tfs = [tf.strip() for tf in args.tfs.split(",") if tf.strip()]
    pairs = [AegisSMCStrategy._normalize_pair(p.strip())
             for p in args.pairs.split(",") if p.strip()] if args.pairs else strategy.pairs

    print(f"Downloading {args.days} days from hyperliquid for {len(pairs)} pairs x {len(tfs)} timeframes")
    for symbol in pairs:
        download_pair(strategy, symbol, tfs, args.days, args.force)
    print("Done.")


if __name__ == "__main__":
    main()
