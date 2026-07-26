import yfinance as yf
import pandas as pd
from indicators import ema, rsi, bollinger_bands

ticker = yf.Ticker("BTC-USD")
df = ticker.history(period="1d", interval="5m")

if not df.empty:
    current_price = df["Close"].iloc[-1]

    df["EMA9"] = ema(df["Close"], 9)
    df["EMA21"] = ema(df["Close"], 21)
    df["EMA50"] = ema(df["Close"], 50)
    bollinger_bands(df)
    df["RSI"] = rsi(df["Close"])

    latest = df.iloc[-1]

    print(f"Time (UTC): {df.index[-1]}")
    print(f"Current Price: ${current_price:,.2f}")
    print(f"EMA 9:  ${latest['EMA9']:,.2f}")
    print(f"EMA 21: ${latest['EMA21']:,.2f}")
    print(f"EMA 50: ${latest['EMA50']:,.2f}")
    print(f"BB Upper: ${latest['BB_Upper']:,.2f}")
    print(f"BB Lower: ${latest['BB_Lower']:,.2f}")
    print(f"RSI (14): {latest['RSI']:.2f}")

    print("\nLast 10 candles (5m):")
    print(df[["Open", "High", "Low", "Close", "Volume", "EMA9", "EMA21", "RSI"]].tail(10))
