"""Analyze simulated trades: RR sweep + expectancy + drawdown report.

Each filled trade stores its full price path (up to SL or data end), so every
RR target can be evaluated without re-simulating.

Usage:
    ./venv/bin/python3 analysis/backtest/report.py --days 30 --rr-sweep 2.5,3.0,4.0
"""
import argparse
import json
import os
import sys

sys.path.insert(0, ".")

import pandas as pd

from analysis.backtest.simulate import RESULTS_DIR

DEFAULT_RR_SWEEP = "2.5,3.0,4.0"


def walk_path(trade, rr_target: float) -> dict:
    direction = trade["direction"]
    entry = trade["entry"]
    sl = trade["sl"]
    risk = trade["risk"]
    tp = entry + risk * rr_target if direction == "long" else entry - risk * rr_target
    mfe = 0.0
    mae = 0.0
    for h, l in trade["path"]:
        if direction == "long":
            mfe = max(mfe, (h - entry) / risk)
            mae = min(mae, (l - entry) / risk)
            if l <= sl:
                return {"outcome": "loss", "r": -1.0, "mfe_r": mfe, "mae_r": mae}
            if h >= tp:
                return {"outcome": "win", "r": rr_target, "mfe_r": mfe, "mae_r": mae}
        else:
            mfe = max(mfe, (entry - l) / risk)
            mae = min(mae, (entry - h) / risk)
            if h >= sl:
                return {"outcome": "loss", "r": -1.0, "mfe_r": mfe, "mae_r": mae}
            if l <= tp:
                return {"outcome": "win", "r": rr_target, "mfe_r": mfe, "mae_r": mae}
    return {"outcome": "open", "r": None, "mfe_r": mfe, "mae_r": mae}


def sweep_stats(trades, rr_target: float) -> dict:
    filled = [t for t in trades if t["filled"]]
    resolved = []
    for t in filled:
        result = walk_path(t, rr_target)
        if result["outcome"] != "open":
            resolved.append(result["r"])
    wins = [r for r in resolved if r > 0]
    losses = [r for r in resolved if r < 0]
    n = len(resolved)
    win_rate = len(wins) / n if n else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    equity = []
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in resolved:
        cumulative += r
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return {
        "rr_target": rr_target,
        "signals": len(trades),
        "filled": len(filled),
        "fill_rate": len(filled) / len(trades) if trades else 0.0,
        "resolved": n,
        "wins": len(wins),
        "losses": len(losses),
        "open": len(filled) - n,
        "win_rate": win_rate,
        "expectancy": sum(resolved) / n if n else 0.0,
        "total_r": cumulative,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf") if gross_win else 0.0,
        "avg_win": gross_win / len(wins) if wins else 0.0,
        "avg_loss": gross_loss / len(losses) if losses else 0.0,
        "max_drawdown_r": max_dd,
    }


def fmt_row(stats: dict) -> str:
    return (
        f"RR {stats['rr_target']:>4} | fill {stats['fill_rate']:5.1%} | "
        f"n {stats['resolved']:>4} ({stats['wins']}W/{stats['losses']}L/{stats['open']}O) | "
        f"WR {stats['win_rate']:5.1%} | expectancy {stats['expectancy']:+.3f}R | "
        f"PF {stats['profit_factor']:.2f} | total {stats['total_r']:+.1f}R | "
        f"maxDD {stats['max_drawdown_r']:.1f}R"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="RR sweep and statistics over simulated trades.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--rr-sweep", default=DEFAULT_RR_SWEEP)
    parser.add_argument("--trades", default="", help="path to trades JSON (default: latest)")
    args = parser.parse_args()

    trades_path = args.trades or os.path.join(RESULTS_DIR, f"trades_{args.days}d.json")
    if not os.path.exists(trades_path):
        print(f"Trades file not found: {trades_path}")
        sys.exit(1)
    with open(trades_path) as f:
        trades = json.load(f)
    rr_sweep = [float(r) for r in args.rr_sweep.split(",") if r.strip()]
    print(f"Loaded {len(trades)} trades from {trades_path}\n")

    print("=" * 90)
    print("  AEGIS V4 BACKTEST — RR SWEEP (no time-stop, hold to SL/TP)")
    print("=" * 90)
    for rr in rr_sweep:
        print(f"  {fmt_row(sweep_stats(trades, rr))}")

    print("\n" + "=" * 90)
    print("  BREAKDOWN PER PAIR (at strategy default RR = 3.0)")
    print("=" * 90)
    pairs = {}
    for t in trades:
        pairs.setdefault(t["pair"], []).append(t)
    for pair in sorted(pairs):
        print(f"  {pair:<16} {fmt_row(sweep_stats(pairs[pair], 3.0))}")

    print("\n" + "=" * 90)
    print("  BREAKDOWN PER TIMEFRAME COMBO (at RR = 3.0)")
    print("=" * 90)
    combos = {}
    for t in trades:
        combos.setdefault(f"{t['tf_htf']}/{t['tf_ltf']}", []).append(t)
    for combo in sorted(combos):
        print(f"  {combo:<16} {fmt_row(sweep_stats(combos[combo], 3.0))}")

    summary_path = os.path.join(RESULTS_DIR, f"summary_{args.days}d.csv")
    rows = [sweep_stats(trades, rr) for rr in rr_sweep]
    pd.DataFrame(rows).to_csv(summary_path, index=False)
    print(f"\nSummary -> {summary_path}")


if __name__ == "__main__":
    main()
