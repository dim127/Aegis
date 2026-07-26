import asyncio
import json
import yfinance as yf
import pandas as pd
from indicators import ema, rsi
from web.server import get_defillama_onchain_data


async def get_avax_conviction_data():
    ticker = yf.Ticker("AVAX-USD")
    df_1h = ticker.history(period="7d", interval="1h")
    df_15m = ticker.history(period="2d", interval="15m")

    if df_1h.empty:
        print("No data found for AVAX.")
        return

    price = df_1h["Close"].iloc[-1]

    df_1h["EMA9"] = ema(df_1h["Close"], 9)
    df_1h["EMA21"] = ema(df_1h["Close"], 21)
    df_1h["EMA50"] = ema(df_1h["Close"], 50)
    df_1h["RSI"] = rsi(df_1h["Close"])
    df_15m["RSI"] = rsi(df_15m["Close"])

    try:
        avax_onchain = await get_defillama_onchain_data("Avalanche")
        onchain_data = json.loads(avax_onchain)
        tvl = onchain_data.get("tvl_usd", 0)
    except Exception:
        tvl = 0

    print("=== AVAX (AVALANCHE) DEEP ANALYSIS ===")
    print(f"AVAX Current Price : ${price:,.2f}")
    print(f"RSI 1h             : {df_1h['RSI'].iloc[-1]:.2f}")
    print(f"RSI 15m            : {df_15m['RSI'].iloc[-1]:.2f}")
    print(f"EMA 9 (1h)         : ${df_1h['EMA9'].iloc[-1]:,.2f}")
    print(f"EMA 21 (1h)        : ${df_1h['EMA21'].iloc[-1]:,.2f}")
    print(f"EMA 50 (1h)        : ${df_1h['EMA50'].iloc[-1]:,.2f}")
    print(f"Avalanche TVL (On-Chain) : ${tvl:,.0f}")

    print("\nSUMMARY:")
    if df_1h["EMA9"].iloc[-1] > df_1h["EMA21"].iloc[-1]:
        print("- Short-term Trend (1H): BULLISH (EMA9 above EMA21)")
    else:
        print("- Short-term Trend (1H): BEARISH (EMA9 below EMA21)")

    if price > df_1h["EMA50"].iloc[-1]:
        print("- Mid-term Trend (1H): Price ABOVE EMA50 (Strengthening)")
    else:
        print("- Mid-term Trend (1H): Price BELOW EMA50 (Weakening)")


if __name__ == "__main__":
    asyncio.run(get_avax_conviction_data())
