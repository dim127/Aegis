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
from strategy.aegis_strategy import AegisSMCStrategy

COMBOS = [("15m", "1m"), ("1h", "5m"), ("4h", "15m")]
LOOKBACK = 150
SIGNAL_COLUMNS = [
    "timestamp", "pair", "tf_htf", "tf_ltf", "direction",
    "entry", "sl", "tp", "risk", "rr",
    "fvg_time", "structure_time", "event_kind",
]
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
        for direction in ("long", "short"):
            if h_end in htf_context_cache[direction]:
                htf_context = htf_context_cache[direction][h_end]
            else:
                htf_context = strategy._htf_context(htf, direction)
                htf_context_cache[direction][h_end] = htf_context
            setup = strategy._check_direction(htf, ltf, direction, tf_htf, tf_ltf,
                                              htf_context=htf_context)
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
                "fvg_time": fvg_time,
                "structure_time": event["index"] if event else None,
                "event_kind": event["kind"] if event else "",
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
