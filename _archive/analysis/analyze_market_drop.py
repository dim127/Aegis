import asyncio
import json
import yfinance as yf
import pandas as pd
from web.server import (
    get_realtime_crypto_prices,
    get_derivatives_metrics,
    get_market_sentiment,
)


async def analyze_drop():
    raw = await get_realtime_crypto_prices("bitcoin,ethereum,solana")
    prices = json.loads(raw)

    btc_price = prices.get("bitcoin", {}).get("usd", 0)
    btc_change = prices.get("bitcoin", {}).get("usd_24h_change", 0)
    eth_price = prices.get("ethereum", {}).get("usd", 0)
    eth_change = prices.get("ethereum", {}).get("usd_24h_change", 0)
    sol_price = prices.get("solana", {}).get("usd", 0)
    sol_change = prices.get("solana", {}).get("usd_24h_change", 0)

    ticker_btc = yf.Ticker("BTC-USD")
    df_btc = ticker_btc.history(period="1d", interval="15m")
    btc_15m_low = df_btc["Low"].min() if not df_btc.empty else 0

    sentiment_raw = await get_market_sentiment()
    sentiment = json.loads(sentiment_raw)

    print("=== MARKET DROP ROOT CAUSE ANALYSIS ===")
    print(f"BTC Price : ${btc_price:,.2f} ({btc_change:+.2f}%) | 15m Low: ${btc_15m_low:,.2f}")
    print(f"ETH Price : ${eth_price:,.2f} ({eth_change:+.2f}%)")
    print(f"SOL Price : ${sol_price:,.2f} ({sol_change:+.2f}%)")
    print(f"Sentiment : {sentiment}")


if __name__ == "__main__":
    asyncio.run(analyze_drop())
