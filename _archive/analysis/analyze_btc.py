import yfinance as yf
import pandas as pd
from indicators import ema, rsi


def main():
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(period="1y", interval="1d")

    if not df.empty:
        current_price = df["Close"].iloc[-1]
        high_1y = df["High"].max()
        low_1y = df["Low"].min()

        df["MA50"] = ema(df["Close"], 50)
        df["MA200"] = ema(df["Close"], 200)
        df["RSI"] = rsi(df["Close"])

        print(f"Current Price: ${current_price:,.2f}")
        print(f"1 Year High: ${high_1y:,.2f}")
        print(f"1 Year Low: ${low_1y:,.2f}")
        print(f"50-day EMA: ${df['MA50'].iloc[-1]:,.2f}")
        print(f"200-day EMA: ${df['MA200'].iloc[-1]:,.2f}")
        print(f"RSI (14): {df['RSI'].iloc[-1]:.2f}")

        print("\nLast 5 days summary:")
        print(df[["Close", "Volume", "MA50", "MA200", "RSI"]].tail(5))


if __name__ == "__main__":
    main()
