import yfinance as yf
import pandas as pd
from indicators import ema, rsi


def main():
    ticker = yf.Ticker("BTC-USD")

    print("=== MULTI-TIMEFRAME BTC ANALYSIS ===")

    for tf, period in [("5m", "1d"), ("15m", "2d"), ("1h", "7d")]:
        df = ticker.history(period=period, interval=tf)
        if df.empty:
            continue

        price = df["Close"].iloc[-1]
        df["EMA9"] = ema(df["Close"], 9)
        df["EMA21"] = ema(df["Close"], 21)
        df["EMA50"] = ema(df["Close"], 50)
        df["RSI"] = rsi(df["Close"])

        ema9 = df["EMA9"].iloc[-1]
        ema21 = df["EMA21"].iloc[-1]
        ema50 = df["EMA50"].iloc[-1]
        rsi_val = df["RSI"].iloc[-1]

        print(f"\nTimeframe: {tf}")
        print(f"BTC Price: ${price:,.2f}")
        print(f"EMA9: ${ema9:,.2f} | EMA21: ${ema21:,.2f} | EMA50: ${ema50:,.2f}")
        print(f"RSI: {rsi_val:.2f}")


if __name__ == "__main__":
    main()
