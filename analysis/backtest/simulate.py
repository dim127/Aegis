"""Simulate SMC setups against subsequent price action.

Rules (matching Aegis SMC philosophy):
- Limit order entry at the FVG midpoint (only fills if price trades through it).
- One position per pair at a time; signals are suppressed while one is open.
- No time-stop: hold until SL or TP.
- If both SL and TP are hit in the same candle, SL wins (conservative).
- A limit order that does not fill within `fill_window` candles is cancelled.
- Win paths are extended until the SL or the cap so higher RR targets can be
  re-evaluated later without a new simulation.

Usage:
    ./venv/bin/python3 analysis/backtest/simulate.py --days 30
    ./venv/bin/python3 analysis/backtest/simulate.py --days 30 --fill-window 120
"""
import argparse
import json
import os
import sys

sys.path.insert(0, ".")

import pandas as pd

from analysis.backtest.scan_history import load_pair_data, RESULTS_DIR

FILL_WINDOW = 60
PATH_CAP = 1440
TRADE_COLUMNS = [
    "signal_ts", "fill_ts", "exit_ts", "pair", "tf_htf", "tf_ltf", "direction",
    "entry", "sl", "tp", "risk", "rr_target", "confluence",
    "filled", "outcome", "r_multiple", "mfe_r", "mae_r",
]


class Position:
    def __init__(self, sig):
        self.pair = sig["pair"]
        self.tf_htf = sig["tf_htf"]
        self.tf_ltf = sig["tf_ltf"]
        self.direction = sig["direction"]
        self.signal_ts = pd.Timestamp(sig["timestamp"])
        self.entry = float(sig["entry"])
        self.sl = float(sig["sl"])
        self.tp = float(sig["tp"])
        self.risk = float(sig["risk"])
        self.rr_target = float(sig["rr"])
        self.confluence = int(sig["confluence"])
        self.filled = False
        self.fill_pos = None
        self.fill_ts = None
        self.filled_by = None
        self.exit_walk_pos = None
        self.outcome = None
        self.exit_pos = None
        self.exit_ts = None
        self.r_multiple = None
        self.path = []

    @property
    def signal_pos(self) -> int:
        return self._signal_pos

    def set_signal_pos(self, pos: int) -> None:
        self._signal_pos = pos

    def try_fill(self, ltf, until_pos, fill_window):
        if self.filled or self.outcome is not None:
            return
        start = self.filled_by + 1 if self.filled_by is not None else self.signal_pos + 1
        end = min(until_pos + 1, self.signal_pos + fill_window + 1, len(ltf))
        for i in range(start, end):
            candle = ltf.iloc[i]
            if self.direction == "long" and candle["Low"] <= self.entry:
                self._fill_at(i, ltf)
                return
            if self.direction == "short" and candle["High"] >= self.entry:
                self._fill_at(i, ltf)
                return

    def _fill_at(self, i, ltf):
        self.filled = True
        self.fill_pos = i
        self.fill_ts = ltf.index[i]
        self.filled_by = i

    def walk(self, ltf, until_pos):
        if not self.filled or self.outcome is not None or len(self.path) >= PATH_CAP:
            return
        start = self.fill_pos if not self.path else self.exit_walk_pos + 1
        end = min(until_pos + 1, len(ltf), start + PATH_CAP)
        for i in range(start, end):
            h = float(ltf.iloc[i]["High"])
            l = float(ltf.iloc[i]["Low"])
            self.path.append([h, l])
            if self.direction == "long":
                if l <= self.sl:
                    self._resolve("loss", -1.0, i, ltf)
                    return
                if h >= self.tp:
                    self._resolve("win", self.rr_target, i, ltf)
                    return
            else:
                if h >= self.sl:
                    self._resolve("loss", -1.0, i, ltf)
                    return
                if l <= self.tp:
                    self._resolve("win", self.rr_target, i, ltf)
                    return
        self.exit_walk_pos = end - 1

    def _resolve(self, outcome, r_multiple, pos, ltf):
        self.outcome = outcome
        self.r_multiple = r_multiple
        self.exit_pos = pos
        self.exit_ts = ltf.index[pos]

    def expire(self, ltf):
        self.outcome = "expired"
        self.exit_ts = ltf.index[min(len(ltf) - 1, self.signal_pos + FILL_WINDOW)]

    def advance(self, ltf, until_pos, fill_window):
        if self.outcome == "expired":
            return
        if not self.filled:
            self.try_fill(ltf, until_pos, fill_window)
            if not self.filled and until_pos - self.signal_pos >= fill_window:
                self.expire(ltf)
                return
        if self.filled:
            self.walk(ltf, until_pos)

    def finalize(self, ltf):
        if self.outcome is None:
            self.outcome = "open"
            self.exit_ts = ltf.index[-1]
        if self.filled and self.path:
            if self.direction == "long":
                mfe = max((h - self.entry) / self.risk for h, _ in self.path)
                mae = min((l - self.entry) / self.risk for _, l in self.path)
            else:
                mfe = max((self.entry - l) / self.risk for _, l in self.path)
                mae = min((self.entry - h) / self.risk for h, _ in self.path)
            self.mfe_r = round(mfe, 4)
            self.mae_r = round(mae, 4)
        else:
            self.mfe_r = None
            self.mae_r = None

    def to_dict(self, include_path: bool = False) -> dict:
        record = {
            "signal_ts": self.signal_ts.isoformat(),
            "fill_ts": self.fill_ts.isoformat() if self.fill_ts is not None else None,
            "exit_ts": self.exit_ts.isoformat() if self.exit_ts is not None else None,
            "pair": self.pair,
            "tf_htf": self.tf_htf,
            "tf_ltf": self.tf_ltf,
            "direction": self.direction,
            "entry": round(self.entry, 8),
            "sl": round(self.sl, 8),
            "tp": round(self.tp, 8),
            "risk": round(self.risk, 8),
            "rr_target": self.rr_target,
            "confluence": self.confluence,
            "filled": self.filled,
            "outcome": self.outcome,
            "r_multiple": self.r_multiple,
            "mfe_r": self.mfe_r,
            "mae_r": self.mae_r,
        }
        if include_path:
            record["path"] = self.path
        return record


def extend_win_paths(positions: list[Position], ltf: pd.DataFrame) -> None:
    """Extend winning paths past the TP candle until the SL or the cap.

    This keeps the RR sweep honest for targets above the strategy default:
    a win at 3R must be re-classified as a loss if the SL is touched before
    price reaches 4R.
    """
    for p in positions:
        if not p.filled or p.outcome != "win" or p.exit_pos is None:
            continue
        end = min(len(ltf), p.exit_pos + PATH_CAP)
        for i in range(p.exit_pos, end):
            h = float(ltf.iloc[i]["High"])
            l = float(ltf.iloc[i]["Low"])
            p.path.append([h, l])
            if p.direction == "long":
                if l <= p.sl:
                    break
            else:
                if h >= p.sl:
                    break


def simulate_group(signals: pd.DataFrame, ltf: pd.DataFrame, fill_window: int) -> list[Position]:
    positions = []
    pos = None
    for _, sig in signals.iterrows():
        sig_ts = pd.Timestamp(sig["timestamp"])
        sig_pos = ltf.index.get_indexer([sig_ts], method="pad")[0]
        if pos is not None:
            pos.advance(ltf, sig_pos, fill_window)
            if pos.outcome is not None:
                pos.finalize(ltf)
                positions.append(pos)
                pos = None
        if pos is None:
            pos = Position(sig)
            pos.set_signal_pos(sig_pos)
    if pos is not None:
        pos.advance(ltf, len(ltf) - 1, fill_window)
        pos.finalize(ltf)
        positions.append(pos)
    extend_win_paths(positions, ltf)
    for p in positions:
        p.finalize(ltf)
    return positions


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate SMC setups from a signals CSV.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--fill-window", type=int, default=FILL_WINDOW)
    parser.add_argument("--signals", default="", help="path to signals CSV (default: latest)")
    args = parser.parse_args()

    signals_path = args.signals or os.path.join(RESULTS_DIR, f"signals_{args.days}d.csv")
    if not os.path.exists(signals_path):
        print(f"Signals file not found: {signals_path}")
        sys.exit(1)
    signals_df = pd.read_csv(signals_path)
    signals_df["timestamp"] = pd.to_datetime(signals_df["timestamp"], utc=True)
    print(f"Loaded {len(signals_df)} signals from {signals_path}")

    all_positions = []
    for (pair, tf_htf, tf_ltf), group in signals_df.groupby(["pair", "tf_htf", "tf_ltf"]):
        ltf = load_pair_data(pair, tf_ltf, args.days)
        if ltf is None:
            continue
        positions = simulate_group(group.sort_values("timestamp"), ltf, args.fill_window)
        # Keep Position objects: the JSON export below needs to re-serialise them
        # with their price paths, which a plain dict can no longer do.
        all_positions.extend(positions)
        print(f"  {pair} {tf_htf}/{tf_ltf}: {len(positions)} trades")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    trades_csv = os.path.join(RESULTS_DIR, f"trades_{args.days}d.csv")
    trades_json = os.path.join(RESULTS_DIR, f"trades_{args.days}d.json")
    pd.DataFrame([p.to_dict() for p in all_positions],
                 columns=TRADE_COLUMNS).to_csv(trades_csv, index=False)
    with open(trades_json, "w") as f:
        json.dump([p.to_dict(include_path=True) for p in all_positions], f)
    print(f"\n{len(all_positions)} trades -> {trades_csv}")
    print(f"path data      -> {trades_json}")


if __name__ == "__main__":
    main()
