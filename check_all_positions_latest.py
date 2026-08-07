"""Live position summary from the exchange (Binance futures)."""
import sys

sys.path.insert(0, ".")

import execution


def main():
    positions = execution.fetch_positions()
    if positions is None:
        print("Gagal mengambil posisi dari exchange (lihat log).")
        return
    open_positions = [
        p for p in positions
        if float(p.get("contracts") or 0) > 0
    ]
    if not open_positions:
        print("Tidak ada posisi terbuka di Binance.")
        return
    for p in open_positions:
        symbol = p.get("symbol")
        side = p.get("side")
        contracts = p.get("contracts")
        entry = p.get("entryPrice")
        mark = p.get("markPrice")
        pnl = p.get("unrealizedPnl")
        print(f"{symbol} | {side.upper()} | {contracts} kontrak | "
              f"entry ${float(entry or 0):.4f} | mark ${float(mark or 0):.4f} | "
              f"uPnL ${float(pnl or 0):.2f}")


if __name__ == "__main__":
    main()
