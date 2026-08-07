"""How the signals Aegis produced are faring against current price.

Aegis places no orders, so there is no position to report. What matters is
whether the setups it called are working: did price reach the entry, and has it
gone on to the target or the stop.
"""
import sys

sys.path.insert(0, ".")

import db
import execution
from notifications.telegram_bot import fmt_price


def _progress(trade: dict, price: float) -> str:
    """Where price sits between the signal's stop and its target, in R."""
    reference = trade.get("fill_price") or trade["entry"]
    risk = abs(reference - trade["sl"])
    if risk <= 0:
        return "risk tidak valid"
    if trade["direction"] == "long":
        if price <= trade["sl"]:
            return "STOP LOSS TERSENTUH"
        if price >= trade["tp"]:
            return "TAKE PROFIT TERSENTUH"
        return f"berjalan ({(price - reference) / risk:+.2f}R)"
    if price >= trade["sl"]:
        return "STOP LOSS TERSENTUH"
    if price <= trade["tp"]:
        return "TAKE PROFIT TERSENTUH"
    return f"berjalan ({(reference - price) / risk:+.2f}R)"


def main():
    signals = db.fetch_trade_journal("PENDING") + db.fetch_trade_journal("TRIGGERED")
    if not signals:
        print("Tidak ada sinyal aktif di journal.")
    else:
        print(f"=== {len(signals)} sinyal aktif ===")
        for trade in signals:
            price = execution.fetch_price(trade["pair"])
            direction = "LONG" if trade["direction"] == "long" else "SHORT"
            print(f"\n{trade['pair']} ({direction}) [{trade['status']}] {trade['tf_combo']}")
            print(f"  Entry {fmt_price(trade['entry'])} | "
                  f"SL {fmt_price(trade['sl'], trade['entry'])} | "
                  f"TP {fmt_price(trade['tp'], trade['entry'])}")
            if price is None:
                print("  Harga tidak tersedia.")
                continue
            print(f"  Harga sekarang {fmt_price(price, trade['entry'])} — {_progress(trade, price)}")

    summary = db.performance_summary()
    if summary["trades"]:
        print(f"\n=== Hasil tercatat ({summary['trades']} sinyal selesai) ===")
        print(f"Win rate  : {summary['win_rate']:.1f}%")
        print(f"Expectancy: {summary['expectancy_r']:+.2f}R")
        print(f"Total     : {summary['total_r']:+.2f}R")
    else:
        print("\nBelum ada sinyal yang selesai — jalankan backtest untuk mengukur kualitas sinyal.")


if __name__ == "__main__":
    main()
