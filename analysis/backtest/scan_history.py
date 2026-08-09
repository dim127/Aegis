"""Replay SMC detection over cached history and emit every valid setup.

For each closed LTF candle the dataframes are truncated exactly like a live
scan at that moment, so the backtest uses identical strategy logic.

Usage:
    ./venv/bin/python3 analysis/backtest/scan_history.py --days 30
    ./venv/bin/python3 analysis/backtest/scan_history.py --days 30 --tf-combo 15m/1m
    ./venv/bin/python3 analysis/backtest/scan_history.py --workers 8
"""
import argparse
import multiprocessing
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

import numpy as np
import pandas as pd

import db
from market_metrics import PositioningSeries, estimate_liquidation_clusters
from strategy.aegis_strategy import AegisSMCStrategy

COMBOS = [("15m", "1m"), ("1h", "5m"), ("4h", "15m")]
LOOKBACK = 150
# 4h is the widest retention Binance serves on the positioning endpoints
# (~31 days). 1h only reaches back ~21 days, short of the OHLCV cache window.
POSITIONING_PERIOD = "4h"
SIGNAL_COLUMNS = [
    "timestamp", "pair", "tf_htf", "tf_ltf", "direction",
    "entry", "sl", "tp", "risk", "rr", "confluence",
    "fvg_time", "structure_time", "event_kind", "reasons",
    # Measured, not gated on: these exist so their edge can be evaluated
    # against outcomes before anything is filtered by them.
    "ls_long_pct", "oi_change_24h_pct", "funding_bp", "funding_z",
    # Two readings of the liquidation-cluster factor, and the stricter FVG
    # timing rule. Recorded so each can be scored before any becomes a gate.
    "cluster_side_sweep", "cluster_side_draw", "fvg_after_confirm", "soft_hits",
]
# Open interest is only available at 4h resolution over a 30-day window, so it
# is a regime measure (building vs unwinding), not per-sweep confirmation.
OI_LOOKBACK_MS = 24 * 60 * 60 * 1000

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load_pair_data(symbol: str, tf: str, days: int) -> pd.DataFrame | None:
    df = db.get_cached_ohlcv(symbol, tf, max_age_minutes=days * 24 * 60)
    if df is None or df.empty:
        return None
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df.index = pd.to_datetime(df.index, utc=True).as_unit("ns")
    return df.sort_index()


def scan_pair_combo(args):
    symbol, tf_htf, tf_ltf, days = args
    strategy = AegisSMCStrategy()
    df_htf = load_pair_data(symbol, tf_htf, days)
    df_ltf = load_pair_data(symbol, tf_ltf, days)
    if df_htf is None or df_ltf is None or len(df_ltf) < 60:
        return []

    htf_ns = df_htf.index.asi8
    ltf_ns = df_ltf.index.asi8
    htf_duration_ns = strategy.TIMEFRAME_DURATIONS[tf_htf].value
    n_ltf = len(df_ltf)

    # Factor 7 IS backtestable: Binance serves ~30 days of long/short history.
    # Run download_positioning.py to populate it. When the series is empty the
    # factor is skipped and a warning is printed, rather than silently scoring
    # every setup one factor lower than it would score live.
    ls_series = PositioningSeries(
        symbol, f"long_short_{getattr(strategy, 'long_short_source', 'top_position')}",
        POSITIONING_PERIOD,
    )
    if getattr(strategy, "long_short_enabled", True) and len(ls_series) == 0:
        print(f"  WARNING {symbol}: no long/short history — factor 7 skipped "
              f"(run download_positioning.py --period {POSITIONING_PERIOD})")
    oi_series = PositioningSeries(symbol, "open_interest", POSITIONING_PERIOD)
    funding_series = PositioningSeries(symbol, "funding_rate", "8h")

    last_emitted = {"long": None, "short": None}
    htf_context_cache = {"long": {}, "short": {}}
    signals = []
    for ltf_pos, ts_ns in enumerate(ltf_ns):
        h_end = int(np.searchsorted(htf_ns, ts_ns - htf_duration_ns, side="right"))
        if h_end < 50:
            continue
        l_end = int(np.searchsorted(ltf_ns, ts_ns, side="right"))
        if l_end < 50:
            continue
        # Ensure no forward-looking HTF candles leak at the very end of the series.
        if h_end > len(df_htf):
            h_end = len(df_htf)
        htf = df_htf.iloc[max(0, h_end - LOOKBACK):h_end]
        ltf = df_ltf.iloc[max(0, l_end - LOOKBACK):l_end]
        # Long/short is replayed as-of the candle (never a later observation).
        # The liquidation cluster estimate is pure OHLCV, so it is included.
        ts_ms = ts_ns // 1_000_000
        market_ctx = {
            "long_short": ls_series.context_as_of(ts_ms)
            if getattr(strategy, "long_short_enabled", True) else None
        }
        if getattr(strategy, "liquidation_enabled", True):
            market_ctx["clusters"] = estimate_liquidation_clusters(ltf, strategy.liquidation_leverage)
        for direction in ("long", "short"):
            if h_end in htf_context_cache[direction]:
                htf_context = htf_context_cache[direction][h_end]
            else:
                htf_context = strategy._htf_context(htf, direction)
                htf_context_cache[direction][h_end] = htf_context
            setup = strategy._check_direction(htf, ltf, direction, tf_htf, tf_ltf,
                                              htf_context=htf_context, market_ctx=market_ctx)
            if not setup.get("valid"):
                continue
            fvg_time = setup["fvg_timestamp"]
            if last_emitted[direction] == fvg_time:
                continue
            last_emitted[direction] = fvg_time
            event = setup["structure_htf"] or setup["structure_ltf"]
            signals.append({
                "timestamp": setup["timestamp"],
                "pair": symbol,
                "tf_htf": tf_htf,
                "tf_ltf": tf_ltf,
                "direction": direction,
                "entry": setup["entry"],
                "sl": setup["sl"],
                "tp": setup["tp"],
                "risk": setup["risk"],
                "rr": setup["rr"],
                "confluence": setup["confluence"],
                "fvg_time": fvg_time,
                "structure_time": event["index"] if event else None,
                "event_kind": event["kind"] if event else "",
                "reasons": "; ".join(setup["reasons"]),
                "ls_long_pct": ls_series.as_of(ts_ms),
                "oi_change_24h_pct": oi_series.change_pct(ts_ms, OI_LOOKBACK_MS),
                "funding_bp": funding_series.as_of(ts_ms),
                "funding_z": funding_series.zscore_as_of(ts_ms),
                "cluster_side_sweep": setup.get("cluster_side_sweep"),
                "cluster_side_draw": setup.get("cluster_side_draw"),
                "fvg_after_confirm": setup.get("fvg_after_confirm"),
                "soft_hits": setup.get("soft_hits"),
            })
    return signals


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan cached history for valid SMC setups.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--tf-combo", default="", help="only scan one combo, e.g. 15m/1m")
    parser.add_argument("--pairs", default="", help="comma separated symbols")
    parser.add_argument("--workers", type=int, default=max(1, os.cpu_count() or 4))
    args = parser.parse_args()

    strategy = AegisSMCStrategy()
    combos = [tuple(c.split("/")) for c in args.tf_combo.split(",")] if args.tf_combo else COMBOS
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()] if args.pairs else strategy.pairs

    tasks = [(sym, tf_htf, tf_ltf, args.days) for sym in pairs for tf_htf, tf_ltf in combos]

    all_signals = []
    with multiprocessing.Pool(processes=min(args.workers, len(tasks))) as pool:
        for i, signals in enumerate(pool.imap_unordered(scan_pair_combo, tasks), 1):
            all_signals.extend(signals)
            print(f"  [{i}/{len(tasks)}] {tasks[i-1][0]} {tasks[i-1][1]}/{tasks[i-1][2]}: {len(signals)} signals")

    if not all_signals:
        print("No signals found.")
        return

    all_signals.sort(key=lambda s: s["timestamp"])
    os.makedirs(RESULTS_DIR, exist_ok=True)
    output_path = os.path.join(RESULTS_DIR, f"signals_{args.days}d.csv")
    pd.DataFrame(all_signals, columns=SIGNAL_COLUMNS).to_csv(output_path, index=False)
    print(f"\n{len(all_signals)} signals -> {output_path}")


if __name__ == "__main__":
    main()
