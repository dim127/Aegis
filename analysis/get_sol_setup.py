import asyncio
import yfinance as yf
import pandas as pd
from indicators import ema, atr, btc_steering_filter
from web.server import get_liquidation_zones


async def get_sol_setup():
    ticker_sol = yf.Ticker("SOL-USD")
    df_sol = ticker_sol.history(period="7d", interval="1h")

    df_sol["ATR"] = atr(df_sol)

    price_sol = df_sol["Close"].iloc[-1]
    atr_sol = df_sol["ATR"].iloc[-1]

    ticker_btc = yf.Ticker("BTC-USD")
    df_btc = ticker_btc.history(period="7d", interval="1h")

    btc_price = df_btc["Close"].iloc[-1]
    btc_filter_pass = btc_steering_filter(df_btc)
    df_btc["EMA9"] = ema(df_btc["Close"], 9)
    df_btc["EMA21"] = ema(df_btc["Close"], 21)
    btc_ema9 = df_btc["EMA9"].iloc[-1]
    btc_ema21 = df_btc["EMA21"].iloc[-1]

    print(f"--- CURRENT MARKET DATA ---")
    print(f"BTC Price: ${btc_price:.2f}")
    print(f"BTC EMA9: ${btc_ema9:.2f} | EMA21: ${btc_ema21:.2f}")
    print(f"BTC Steering Filter: {'PASS (Bullish)' if btc_filter_pass else 'FAIL (Bearish - Caution)'}")
    print(f"--- SOLANA DATA ---")
    print(f"SOL Price: ${price_sol:.2f}")
    print(f"SOL ATR (14): ${atr_sol:.2f}")

    entry_1 = price_sol
    entry_2 = price_sol - (atr_sol * 0.8)
    avg_entry = (entry_1 + entry_2) / 2

    sl_distance = atr_sol * 1.5
    stop_loss = avg_entry - sl_distance

    tp_1 = avg_entry + (sl_distance * 1.5)
    tp_2 = avg_entry + (sl_distance * 2.5)

    print(f"--- TRADING SETUP (LONG) ---")
    print(f"Tranche 1 (50%): ${entry_1:.2f} (Current Price)")
    print(f"Tranche 2 (50%): ${entry_2:.2f} (Liquidity Dip Zone)")
    print(f"Avg Entry      : ${avg_entry:.2f}")
    print(f"Stop Loss      : ${stop_loss:.2f} (Buffer 1.5x ATR = ${sl_distance:.2f})")
    print(f"Take Profit 1  : ${tp_1:.2f} (RR 1:1.5)")
    print(f"Take Profit 2  : ${tp_2:.2f} (RR 1:2.5)")


if __name__ == "__main__":
    asyncio.run(get_sol_setup())
