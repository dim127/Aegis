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


def fetch_binance_window(exchange, symbol: str, tf: str, since_ms: int, until_ms: int) -> list:
    candles = []
    cursor = since_ms
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, tf, since=cursor, limit=1500)
        if not batch:
            break
        candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        time.sleep(0.15)
    return [c for c in candles if since_ms <= c[0] < until_ms]


def download_pair(strategy, symbol: str, tfs, days: int, force: bool) -> None:
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    until_ms = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp() * 1000)
    exchange = ccxt.binanceusdm({"enableRateLimit": True, "timeout": 30000})
    for tf in tfs:
        if not force and has_cached(symbol, tf, days):
            print(f"  {symbol} {tf}: cached, skipping")
            continue
        try:
            candles = fetch_binance_window(exchange, symbol, tf, since_ms, until_ms)
        except Exception as exc:
            print(f"  {symbol} {tf}: failed ({exc})")
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

    print(f"Downloading {args.days} days from binance for {len(pairs)} pairs x {len(tfs)} timeframes")
    for symbol in pairs:
        download_pair(strategy, symbol, tfs, args.days, args.force)
    print("Done.")


if __name__ == "__main__":
    main()
