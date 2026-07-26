import sys
import yfinance as yf
import pandas as pd
from indicators import ema, rsi


def get_signal(symbol="BTC-USD", interval="5m"):
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="1d", interval=interval)

    if df.empty:
        print(f"No data for {symbol}")
        return

    df["EMA9"] = ema(df["Close"], 9)
    df["EMA21"] = ema(df["Close"], 21)
    df["RSI"] = rsi(df["Close"])

    price = df["Close"].iloc[-1]
    ema9_val = df["EMA9"].iloc[-1]
    ema21_val = df["EMA21"].iloc[-1]
    rsi_val = df["RSI"].iloc[-1]

    score = 0
    reasons = []

    if price > ema9_val and ema9_val > ema21_val:
        score += 2
        reasons.append("Price & EMA9 above EMA21 (Strong Uptrend)")
    elif price < ema9_val and ema9_val < ema21_val:
        score -= 2
        reasons.append("Price & EMA9 below EMA21 (Strong Downtrend)")

    if rsi_val < 30:
        score += 2
        reasons.append(f"RSI Oversold ({rsi_val:.1f}) - Potential Rebound")
    elif rsi_val > 70:
        score -= 2
        reasons.append(f"RSI Overbought ({rsi_val:.1f}) - Potential Correction")
    elif 45 <= rsi_val <= 55:
        reasons.append(f"RSI Neutral ({rsi_val:.1f})")

    if score >= 2:
        signal_status = "BUY (LONG)"
        color_code = "\033[92m"
    elif score <= -2:
        signal_status = "SELL (SHORT)"
        color_code = "\033[91m"
    else:
        signal_status = "WAIT & SEE (NEUTRAL)"
        color_code = "\033[93m"

    reset_code = "\033[0m"

    print("=" * 45)
    print(f"TRADING SIGNAL [{symbol}] ({interval})")
    print("=" * 45)
    print(f"Current Price  : ${price:,.2f}")
    print(f"Signal Status  : {color_code}{signal_status}{reset_code}")
    print("-" * 45)
    print("Indicator Reasons:")
    for r in reasons:
        print(f"  - {r}")
    print("=" * 45)


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC-USD"
    interval = sys.argv[2] if len(sys.argv) > 2 else "5m"
    get_signal(symbol, interval)
