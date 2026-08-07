"""Measure whether a positioning factor actually predicts outcomes.

This exists because adding data is easy and adding *edge* is not. Factor 7 is
scored as confluence but never gated on, so turning it on or off produces
identical signals — the only honest test is whether its value separates winners
from losers.

Every split is reported with its sample size and a permutation p-value, because
at n=20 a 15-point win-rate gap is entirely ordinary noise.

Usage:
    ./venv/bin/python3 analysis/backtest/factor_edge.py --days 30
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def permutation_p(a: np.ndarray, b: np.ndarray, iterations: int = 20000) -> float:
    """Two-sided p-value for a difference in means, by label shuffling.

    Makes no normality assumption, which matters for R-multiples: they are
    bimodal (roughly -1 or +RR), not remotely bell-shaped.
    """
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    observed = abs(a.mean() - b.mean())
    pool = np.concatenate([a, b])
    n = len(a)
    rng = np.random.default_rng(0)
    hits = 0
    for _ in range(iterations):
        rng.shuffle(pool)
        if abs(pool[:n].mean() - pool[n:].mean()) >= observed:
            hits += 1
    return hits / iterations


def describe(label: str, group: pd.DataFrame) -> str:
    if len(group) == 0:
        return f"  {label:<34} n=0"
    r = group["r_multiple"]
    wr = (group["outcome"] == "win").mean() * 100
    return (f"  {label:<34} n={len(group):<4} WR {wr:5.1f}%  "
            f"expectancy {r.mean():+.3f}R  total {r.sum():+.1f}R")


def split_report(title: str, frame: pd.DataFrame, mask: pd.Series,
                 yes_label: str, no_label: str) -> None:
    yes, no = frame[mask], frame[~mask]
    print(f"\n{title}")
    print(describe(yes_label, yes))
    print(describe(no_label, no))
    if len(yes) and len(no):
        p = permutation_p(yes["r_multiple"].to_numpy(), no["r_multiple"].to_numpy())
        gap = yes["r_multiple"].mean() - no["r_multiple"].mean()
        verdict = "SIGNIFIKAN" if p < 0.05 else ("lemah" if p < 0.20 else "TIDAK ADA SINYAL")
        print(f"  {'>> selisih':<34} {gap:+.3f}R   p={p:.3f}   [{verdict}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test factor edge against outcomes.")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    sig_path = os.path.join(RESULTS_DIR, f"signals_{args.days}d.csv")
    trade_path = os.path.join(RESULTS_DIR, f"trades_{args.days}d.json")
    for path in (sig_path, trade_path):
        if not os.path.exists(path):
            print(f"Missing {path} — run scan_history.py and simulate.py first")
            sys.exit(1)

    sig = pd.read_csv(sig_path)
    sig["timestamp"] = pd.to_datetime(sig["timestamp"], utc=True)
    trades = pd.DataFrame([{k: v for k, v in p.items() if k != "path"}
                           for p in json.load(open(trade_path))])
    trades["signal_ts"] = pd.to_datetime(trades["signal_ts"], utc=True)

    join_cols = ["timestamp", "pair", "direction", "tf_htf", "tf_ltf"]
    extra = [c for c in ("ls_long_pct", "oi_change_24h_pct", "funding_bp", "funding_z",
                         "event_kind") if c in sig.columns]
    merged = trades.merge(sig[join_cols + extra], left_on=["signal_ts", "pair", "direction", "tf_htf", "tf_ltf"],
                          right_on=join_cols, how="left")
    resolved = merged[merged["outcome"].isin(["win", "loss"])].copy()

    print("=" * 78)
    print(f"  APAKAH DATA MENAMBAH EDGE?  ({len(resolved)} trade selesai dari {len(merged)} posisi)")
    print("=" * 78)
    if len(resolved) == 0:
        print("Tidak ada trade selesai."); return
    print(describe("SEMUA TRADE", resolved))

    if "ls_long_pct" in resolved.columns and resolved["ls_long_pct"].notna().any():
        d = resolved[resolved["ls_long_pct"].notna()].copy()
        # Contrarian: crowd positioned opposite to the trade direction.
        crowd_long = d["ls_long_pct"] > 50.0
        d["contrarian"] = np.where(d["direction"] == "long", ~crowd_long, crowd_long)
        split_report("[Faktor 7] Crowd berlawanan arah trade (contrarian)",
                     d, d["contrarian"], "contrarian (mendukung)", "searah crowd")

        extreme = (d["ls_long_pct"] > 60.0) | (d["ls_long_pct"] < 40.0)
        split_report("[Faktor 7] Posisi crowd ekstrem (>60% atau <40%)",
                     d, extreme, "ekstrem", "netral 40-60%")

    if "oi_change_24h_pct" in resolved.columns and resolved["oi_change_24h_pct"].notna().any():
        d = resolved[resolved["oi_change_24h_pct"].notna()].copy()
        split_report("[Open Interest] Posisi diurai 24j terakhir (OI turun)",
                     d, d["oi_change_24h_pct"] < 0, "OI turun (unwinding)", "OI naik (building)")
        split_report("[Open Interest] Perubahan tajam (|delta| > 3%)",
                     d, d["oi_change_24h_pct"].abs() > 3.0, "|delta| > 3%", "|delta| <= 3%")

    if "funding_z" in resolved.columns and resolved["funding_z"].notna().any():
        d = resolved[resolved["funding_z"].notna()].copy()
        # Contrarian: high funding means longs are paying, so it favours shorts.
        d["funding_supports"] = np.where(d["direction"] == "long", d["funding_z"] < 0,
                                         d["funding_z"] > 0)
        split_report("[Funding] Funding mendukung arah trade (contrarian)",
                     d, d["funding_supports"], "funding mendukung", "funding melawan")
        split_report("[Funding] Funding ekstrem (|z| > 1)",
                     d, d["funding_z"].abs() > 1.0, "|z| > 1", "|z| <= 1")

    if "event_kind" in resolved.columns:
        d = resolved[resolved["event_kind"].notna()].copy()
        split_report("[Struktur] CHOCH/BOS vs BREAK tanpa tren",
                     d, d["event_kind"].isin(["CHOCH", "BOS"]), "CHOCH atau BOS", "BREAK (tanpa tren)")

    if "confluence" in resolved.columns:
        split_report("[Confluence] Skor tinggi vs rendah",
                     resolved, resolved["confluence"] >= 5, "confluence >= 5", "confluence <= 4")

    print("\n" + "=" * 78)
    print("  Catatan: p >= 0.05 berarti perbedaan sebesar itu wajar muncul dari")
    print("  keberuntungan saja. Jangan jadikan filter tanpa sampel jauh lebih besar.")
    print("=" * 78)


if __name__ == "__main__":
    main()
