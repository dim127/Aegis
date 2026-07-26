import yfinance as yf
import pandas as pd
from indicators import ema, rsi
from config import get_trades

ticker = yf.Ticker("BTC-USD")
df = ticker.history(period="1d", interval="1m")

trade = get_trades()["btc_long"]
TP1 = trade["tp1"]
SL = trade["sl"]
ENTRY_AVG = trade["entry"]

if not df.empty:
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    current_price = latest["Close"]
    price_change = current_price - prev["Close"]
    volume = latest["Volume"]

    df5 = ticker.history(period="1d", interval="5m")
    df5["EMA9"] = ema(df5["Close"], 9)
    df5["EMA21"] = ema(df5["Close"], 21)
    df5["RSI"] = rsi(df5["Close"])

    distance_to_tp = TP1 - current_price
    distance_to_sl = current_price - SL
    total_range = TP1 - ENTRY_AVG
    current_gain = current_price - ENTRY_AVG
    tp_progress = max(0.0, min(100.0, (current_gain / total_range) * 100)) if total_range > 0 else 0

    print(f"Time (UTC)      : {df.index[-1].strftime('%H:%M:%S')}")
    print(f"BTC Price       : ${current_price:,.2f} ({'+' if price_change >= 0 else ''}{price_change:,.2f})")
    print(f"TP1 Progress    : {tp_progress:.1f}% (${distance_to_tp:,.2f} to $65,450)")
    print(f"SL Distance     : +${distance_to_sl:,.2f} above $64,650")
    print(f"RSI 5m          : {df5['RSI'].iloc[-1]:.2f}")
    print(f"EMA9 (5m)       : ${df5['EMA9'].iloc[-1]:,.2f}")

    if current_price >= TP1:
        print("\nSTATUS: TAKE PROFIT 1 ($65,450) HIT! POSITION CLOSED IN PROFIT")
    elif current_price <= SL:
        print("\nSTATUS: STOP LOSS ($64,650) HIT. POSITION CLOSED")
