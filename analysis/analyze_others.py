import yfinance as yf
import pandas as pd
from indicators import ema, rsi, cvd_bias

coins = ["BNB-USD", "DOT-USD", "XRP-USD", "ADA-USD"]
print("=== ALTCOIN ANALYSIS ===")

for coin in coins:
    try:
        df = yf.Ticker(coin).history(period="3d", interval="1h")
        if df.empty:
            continue

        df["EMA9"] = ema(df["Close"], 9)
        df["EMA21"] = ema(df["Close"], 21)
        df["RSI"] = rsi(df["Close"])

        cvd_val = cvd_bias(df)

        price = df["Close"].iloc[-1]
        ema9_val = df["EMA9"].iloc[-1]
        ema21_val = df["EMA21"].iloc[-1]
        rsi_val = df["RSI"].iloc[-1]

        print(f"\n[{coin}]")
        print(f"Price    : ${price:.4f}")
        print(f"Trend    : {'Bullish (EMA9 > EMA21)' if ema9_val > ema21_val else 'Bearish (EMA9 < EMA21)'}")
        print(f"RSI 1H   : {rsi_val:.1f} {'(Overbought)' if rsi_val > 70 else '(Oversold)' if rsi_val < 30 else '(Neutral)'}")
        print(f"CVD Bias : {'BUYERS (Accumulation)' if cvd_val == 'BUYERS' else 'SELLERS (Distribution)'}")

    except Exception as e:
        print(f"Error analyzing {coin}: {e}")
