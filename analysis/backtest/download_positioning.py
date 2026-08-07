"""Download Binance positioning history so the backtest can score factor 7.

The replay used to hardcode `long_short = None` on the assumption that no
historical data existed. It does: the futures/data endpoints serve roughly 30
days, which covers the OHLCV cache window. Without this the backtest scored
every setup with one fewer confluence factor than live, so any threshold tuned
offline was calibrated against a different signal than the one that trades.

Usage:
    ./venv/bin/python3 analysis/backtest/download_positioning.py
    ./venv/bin/python3 analysis/backtest/download_positioning.py --period 15m
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import db
import market_metrics as mm
from strategy.aegis_strategy import AegisSMCStrategy


def _fmt(ms) -> str:
    if ms is None:
        return "-"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download long/short positioning history.")
    parser.add_argument("--period", default="1h", help="1h, 4h, 15m, 5m, 30m, 1d")
    parser.add_argument("--limit", type=int, default=500, help="max 500 per Binance")
    parser.add_argument("--source", default="", help="top_position | top_account | global_account")
    parser.add_argument("--pairs", default="", help="comma separated symbols")
    parser.add_argument("--open-interest", action="store_true",
                        help="also download open interest history")
    parser.add_argument("--funding", action="store_true",
                        help="also download funding rate history (~166 days)")
    args = parser.parse_args()

    strategy = AegisSMCStrategy(exchange=object())
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()] or strategy.pairs
    source = args.source or strategy.long_short_source
    key, endpoint = mm._resolve_source(source)

    print(f"Source: {key} ({endpoint}) | period {args.period} | {len(pairs)} pairs\n")
    total = 0
    for i, symbol in enumerate(pairs, 1):
        saved = mm.download_long_short_history(symbol, args.period, args.limit, key)
        cov = db.positioning_coverage(symbol, f"long_short_{key}", args.period)
        span_days = ((cov["last"] - cov["first"]) / 86400000) if cov["rows"] > 1 else 0
        print(f"  [{i}/{len(pairs)}] {symbol:<18} +{saved:<4} rows | "
              f"{_fmt(cov['first'])} -> {_fmt(cov['last'])} ({span_days:.0f}d)")
        total += saved
        time.sleep(0.25)

    print(f"\n{total} rows saved to positioning_history "
          f"(metric long_short_{key}, period {args.period})")

    if args.open_interest:
        print(f"\nOpen interest | period {args.period}")
        oi_total = 0
        for i, symbol in enumerate(pairs, 1):
            saved = mm.download_open_interest_history(symbol, args.period, args.limit)
            cov = db.positioning_coverage(symbol, "open_interest", args.period)
            span_days = ((cov["last"] - cov["first"]) / 86400000) if cov["rows"] > 1 else 0
            print(f"  [{i}/{len(pairs)}] {symbol:<18} +{saved:<4} rows | "
                  f"{_fmt(cov['first'])} -> {_fmt(cov['last'])} ({span_days:.0f}d)")
            oi_total += saved
            time.sleep(0.25)
        print(f"\n{oi_total} rows saved to positioning_history "
              f"(metric open_interest, period {args.period})")

    if args.funding:
        print("\nFunding rate | period 8h (basis points)")
        fr_total = 0
        for i, symbol in enumerate(pairs, 1):
            saved = mm.download_funding_history(symbol, 1000)
            cov = db.positioning_coverage(symbol, "funding_rate", "8h")
            span_days = ((cov["last"] - cov["first"]) / 86400000) if cov["rows"] > 1 else 0
            print(f"  [{i}/{len(pairs)}] {symbol:<18} +{saved:<4} rows | "
                  f"{_fmt(cov['first'])} -> {_fmt(cov['last'])} ({span_days:.0f}d)")
            fr_total += saved
            time.sleep(0.25)
        print(f"\n{fr_total} rows saved to positioning_history (metric funding_rate, period 8h)")


if __name__ == "__main__":
    main()
