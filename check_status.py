"""Status checker for journaled trades (Binance futures)."""
import sys

sys.path.insert(0, ".")

import db
import execution
from notifications.telegram_bot import fmt_price


def main():
    trades = db.fetch_trade_journal("OPEN") + db.fetch_trade_journal("PLACED")
    if not trades:
        print("Tidak ada trade aktif di journal.")
        return
    for trade in trades:
        symbol = trade["pair"]
        price = execution.fetch_price(symbol)
        direction = "LONG" if trade["direction"] == "long" else "SHORT"
        print(f"\n=== {symbol} ({direction}) [{trade['status']}] ===")
        if price is None:
            print("  Harga tidak tersedia.")
            continue
        reference = trade.get("fill_price") or trade["entry"]
        print(f"Current price: ${fmt_price(price)}")
        print(f"Entry: ${fmt_price(trade['entry'])} | SL: ${fmt_price(trade['sl'])} "
              f"| TP: ${fmt_price(trade['tp'])}")
        if trade["direction"] == "long":
            if price <= trade["sl"]:
                print("STATUS: STOP LOSS HIT")
            elif price >= trade["tp"]:
                print("STATUS: TAKE PROFIT HIT")
            else:
                pnl = (price - reference) / (reference - trade["sl"])
                print(f"STATUS: ACTIVE ({pnl:+.2f}R)")
        else:
            if price >= trade["sl"]:
                print("STATUS: STOP LOSS HIT")
            elif price <= trade["tp"]:
                print("STATUS: TAKE PROFIT HIT")
            else:
                pnl = (reference - price) / (trade["sl"] - reference)
                print(f"STATUS: ACTIVE ({pnl:+.2f}R)")

    summary = db.performance_summary()
    if summary["trades"]:
        print(f"\n=== Realized ({summary['trades']} closed) ===")
        print(f"Win rate: {summary['win_rate']:.1f}% | "
              f"Expectancy: {summary['expectancy_r']:+.2f}R | "
              f"Total: {summary['total_r']:+.2f}R")


if __name__ == "__main__":
    main()
