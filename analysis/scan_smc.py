import sys
sys.path.insert(0, ".")

from strategy.aegis_strategy import AegisSMCStrategy


def scan_smc():
    strategy = AegisSMCStrategy()
    bases = [p.split("/")[0] for p in strategy.pairs]
    print("=" * 62)
    print("  AEGIS V4 — SMC SCANNER (15M + 1M)")
    print(f"  Pairs: {' '.join(bases)} | RR Target: 1:{strategy.rr_target:.0f}")
    print("=" * 62)

    results = strategy.analyze()

    if not results:
        print("\n  NO TRADE - No valid SMC setup found.")
        print("=" * 62)
        return

    for s in results:
        base = s["base"]
        dir_label = "LONG" if s["direction"] == "long" else "SHORT"
        print(f"\n{'=' * 50}")
        print(f"  {base} | {dir_label}")
        print(f"{'=' * 50}")
        print(f"HTF Bias (15M): {s['htf_bias_text']}")
        print(f"LTF Confirmation (1M): {s['ltf_conf_text']}")
        print(f"  Take Profit: ${s['tp']:.2f} → 1:{s['rr']:.2f} RR")
        print()
        print("Trade Setup:")
        print(f"  * Action: {s['action']}")
        print(f"  * Entry Price: ${s['entry']:.2f}")
        print(f"  * Stop Loss: ${s['sl']:.2f}")
        print(f"  * Take Profit: ${s['tp']:.2f}")
        print(f"  * Risk-to-Reward Ratio: 1:{s['rr']:.2f}")
        print()
        print(f"Management Rules: {s['management_rules']}")

    print(f"\n{'=' * 62}")
    print(f"  Total setups found: {len(results)}")
    print("=" * 62)


if __name__ == "__main__":
    scan_smc()
