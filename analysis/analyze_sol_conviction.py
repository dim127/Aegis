import asyncio
import json
import yfinance as yf
import pandas as pd
from indicators import ema, rsi
from web.server import (
    get_realtime_crypto_prices,
    get_derivatives_metrics,
    get_liquidation_zones,
    get_defillama_onchain_data,
    get_market_sentiment,
)


async def get_sol_conviction_data():
    ticker = yf.Ticker("SOL-USD")
    df_1h = ticker.history(period="7d", interval="1h")
    df_15m = ticker.history(period="2d", interval="15m")

    price = df_1h["Close"].iloc[-1]

    df_1h["EMA9"] = ema(df_1h["Close"], 9)
    df_1h["EMA21"] = ema(df_1h["Close"], 21)
    df_1h["EMA50"] = ema(df_1h["Close"], 50)
    df_1h["RSI"] = rsi(df_1h["Close"])
    df_15m["RSI"] = rsi(df_15m["Close"])

    sol_onchain = await get_defillama_onchain_data("Solana")
    onchain_data = json.loads(sol_onchain)

    print(f"SOL Current Price : ${price:,.2f}")
    print(f"RSI 1h            : {df_1h['RSI'].iloc[-1]:.2f}")
    print(f"RSI 15m           : {df_15m['RSI'].iloc[-1]:.2f}")
    print(f"EMA 9 (1h)        : ${df_1h['EMA9'].iloc[-1]:,.2f}")
    print(f"EMA 21 (1h)       : ${df_1h['EMA21'].iloc[-1]:,.2f}")
    print(f"EMA 50 (1h)       : ${df_1h['EMA50'].iloc[-1]:,.2f}")
    print(f"Solana On-Chain TVL: ${onchain_data.get('tvl_usd', 0):,.0f}")


if __name__ == "__main__":
    asyncio.run(get_sol_conviction_data())
