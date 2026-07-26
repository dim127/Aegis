import yfinance as yf
import pandas as pd
from indicators import ema, rsi, cvd_bias

try:
    df_doge = yf.Ticker("DOGE-USD").history(period="3d", interval="1h")

    df_doge["EMA9"] = ema(df_doge["Close"], 9)
    df_doge["EMA21"] = ema(df_doge["Close"], 21)
    df_doge["RSI"] = rsi(df_doge["Close"])

    cvd_val = cvd_bias(df_doge)

    price = df_doge["Close"].iloc[-1]
    ema9_val = df_doge["EMA9"].iloc[-1]
    ema21_val = df_doge["EMA21"].iloc[-1]
    rsi_val = df_doge["RSI"].iloc[-1]

    print("--- DOGE ANALYSIS ---")
    print(f"Price: ${price:.4f}")
    print(f"EMA9: ${ema9_val:.4f} | EMA21: ${ema21_val:.4f}")
    print(f"Trend: {'Bearish' if ema9_val < ema21_val else 'Bullish'}")
    print(f"RSI 1H: {rsi_val:.1f}")
    print(f"CVD Bias: {'SELLERS (Distribution)' if cvd_val == 'SELLERS' else 'BUYERS (Accumulation)'}")

except Exception as e:
    print("Error:", e)
