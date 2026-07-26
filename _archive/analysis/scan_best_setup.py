import yfinance as yf
import pandas as pd
from indicators import ema, rsi
from config import DEFAULT_SYMBOLS


def main():
    print("=== SCANNING TOP SETUP TODAY (BTC, ETH, SOL) ===")

    results = {}

    for sym in DEFAULT_SYMBOLS:
        ticker = yf.Ticker(sym)
        df_1d = ticker.history(period="1mo", interval="1d")
        df_1h = ticker.history(period="7d", interval="1h")

        if df_1h.empty:
            continue

        price = df_1h["Close"].iloc[-1]

        df_1h["EMA9"] = ema(df_1h["Close"], 9)
        df_1h["EMA21"] = ema(df_1h["Close"], 21)
        df_1h["EMA50"] = ema(df_1h["Close"], 50)
        df_1h["RSI"] = rsi(df_1h["Close"])

        ema9_val = df_1h["EMA9"].iloc[-1]
        ema21_val = df_1h["EMA21"].iloc[-1]
        ema50_val = df_1h["EMA50"].iloc[-1]
        rsi_val = df_1h["RSI"].iloc[-1]

        high_1mo = df_1d["High"].max()
        low_1mo = df_1d["Low"].min()

        results[sym] = {
            "price": price,
            "ema9_1h": ema9_val,
            "ema21_1h": ema21_val,
            "ema50_1h": ema50_val,
            "rsi_1h": rsi_val,
            "high_1mo": high_1mo,
            "low_1mo": low_1mo,
            "high_24h": df_1h["High"].tail(24).max(),
            "low_24h": df_1h["Low"].tail(24).min(),
        }

        print(f"\n[{sym}]")
        print(f"Real-Time Price : ${price:,.2f}")
        print(f"24h Range       : ${results[sym]['low_24h']:,.2f} - ${results[sym]['high_24h']:,.2f}")
        print(f"RSI (1h)        : {rsi_val:.2f}")
        print(f"EMA 9/21/50 (1h): ${ema9_val:,.2f} / ${ema21_val:,.2f} / ${ema50_val:,.2f}")


if __name__ == "__main__":
    main()
