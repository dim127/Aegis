import sys
sys.path.insert(0, ".")

from strategy.aegis_strategy import AegisSMCStrategy
from notifications.telegram_bot import fmt_price


def scan_smc():
    strategy = AegisSMCStrategy()
    bases = [p.split("/")[0] for p in strategy.pairs]
    print("=" * 62)
    print("  AEGIS V4 — SMC MULTI-TIMEFRAME SCANNER")
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
        print(f"  {base} [{s['tf_combo']}] | {dir_label}")
        print(f"{'=' * 50}")
        print(f"1 POI     : {s['poi_label']}")
        print(f"2 Sweep   : {s['sweep_label']}")
        print(f"3 MSS     : {s['mss_label']}")
        print(f"4 OTE     : {s['ote_label']}")
        print(f"5 Entry   : {s['fvg_label']}")
        print()
        print("Trade Setup:")
        print(f"  * Action: {s['action']}")
        print(f"  * Entry Price: {fmt_price(s['entry'])}")
        print(f"  * Stop Loss: {fmt_price(s['sl'], s['entry'])}")
        print(f"  * Take Profit: {fmt_price(s['tp'], s['entry'])}")
        print(f"  * Risk: {s.get('risk_pct', 0):.2f}% of price")
        print(f"  * Risk-to-Reward Ratio: 1:{s['rr']:.2f}  (TP: {s['tp_label']})")
        print(f"Management Rules: {s['management_rules']}")

    print(f"\n{'=' * 62}")
    print(f"  Total setups found: {len(results)}")
    print("=" * 62)


if __name__ == "__main__":
    scan_smc()
