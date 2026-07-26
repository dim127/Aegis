import yfinance as yf
import pandas as pd
from indicators import ema, rsi
from config import DEFAULT_SYMBOLS


def main():
    print("=== MARKET SCANNER RESULTS ===")

    for sym in DEFAULT_SYMBOLS:
        ticker = yf.Ticker(sym)
        df = ticker.history(period="2d", interval="15m")
        if df.empty:
            continue

        price = df["Close"].iloc[-1]
        df["EMA9"] = ema(df["Close"], 9)
        df["EMA21"] = ema(df["Close"], 21)
        df["EMA50"] = ema(df["Close"], 50)
        df["RSI"] = rsi(df["Close"])

        ema9_val = df["EMA9"].iloc[-1]
        ema21_val = df["EMA21"].iloc[-1]
        ema50_val = df["EMA50"].iloc[-1]
        rsi_val = df["RSI"].iloc[-1]

        print(f"\n[{sym}]")
        print(f"Price: ${price:,.2f}")
        print(f"EMA9: ${ema9_val:,.2f} | EMA21: ${ema21_val:,.2f} | EMA50: ${ema50_val:,.2f}")
        print(f"RSI: {rsi_val:.2f}")

        if rsi_val < 35:
            print(">>> POTENTIAL: Oversold Dip-Buy / Rebound (15m)")
        elif rsi_val > 65:
            print(">>> POTENTIAL: Overbought Breakout/Pullback (15m)")
        elif ema9_val > ema21_val and ema21_val > ema50_val:
            print(">>> POTENTIAL: Strong Bullish Momentum Trend-Follow (15m)")
        elif ema9_val < ema21_val and ema21_val < ema50_val:
            print(">>> POTENTIAL: Bearish Downtrend Breakdown (15m)")
        else:
            print(">>> POTENTIAL: Rangebound / Sideways (15m)")


if __name__ == "__main__":
    main()
