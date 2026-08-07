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
        print(f"HTF Bias: {s['htf_bias_text']}")
        print(f"LTF Confirmation: {s['ltf_conf_text']}")
        print(f"  Take Profit: ${fmt_price(s['tp'], s['entry'])} → "
              f"1:{s['rr']:.2f} RR (net 1:{s.get('rr_net', s['rr']):.2f})")
        print()
        print(f"Confluence Factors ({s['confluence']}/8):")
        for reason in s["reasons"]:
            print(f"  * {reason}")
        print()
        print("Trade Setup:")
        print(f"  * Action: {s['action']}")
        print(f"  * Entry Price: ${fmt_price(s['entry'])}")
        print(f"  * Stop Loss: ${fmt_price(s['sl'], s['entry'])}")
        print(f"  * Take Profit: ${fmt_price(s['tp'], s['entry'])}")
        print(f"  * Risk: {s.get('risk_pct', 0):.2f}% of price")
        print(f"  * Risk-to-Reward Ratio: 1:{s['rr']:.2f} (net 1:{s.get('rr_net', s['rr']):.2f})")
        ctx = s.get("context") or {}
        if ctx:
            print()
            print("Konteks Pasar (data asli — informasi, bukan filter):")
            if ctx.get("open_interest") is not None:
                chg = ctx.get("oi_change_24h_pct")
                arah = "" if chg is None else f"  ({chg:+.2f}% / 24j, {'posisi dibangun' if chg > 0 else 'posisi diurai'})"
                print(f"  * Open Interest : {ctx['open_interest']:,.0f} kontrak{arah}")
            if ctx.get("funding_bp") is not None:
                z = ctx.get("funding_z")
                zt = "" if z is None else f", z={z:+.2f} vs norma pair"
                sisi = "long bayar short" if ctx["funding_bp"] > 0 else "short bayar long"
                print(f"  * Funding       : {ctx['funding_bp']:+.3f} bp ({sisi}{zt})")
            if ctx.get("volume_ratio") is not None:
                print(f"  * Volume        : {ctx['volume_ratio']:.2f}x rata-rata 24 candle")
            liq = ctx.get("liquidity")
            if liq:
                share = liq.get("bid_share")
                if share is not None:
                    dom = "bid (beli) lebih tebal" if share > 0.5 else "ask (jual) lebih tebal"
                    print(f"  * Order book    : {share*100:.0f}% bid dalam ±{liq['within_pct']:.0f}% — {dom}")
                for key, label in (("bid_wall", "Dinding bid"), ("ask_wall", "Dinding ask")):
                    w = liq.get(key)
                    if w:
                        print(f"    - {label:12}: ${fmt_price(w['price'], s['entry'])} "
                              f"({w['dist_pct']:+.2f}% dari entry, {w['qty']:,.1f} kontrak)")
        print()
        print(f"Management Rules: {s['management_rules']}")

    print(f"\n{'=' * 62}")
    print(f"  Total setups found: {len(results)}")
    print("=" * 62)


if __name__ == "__main__":
    scan_smc()
