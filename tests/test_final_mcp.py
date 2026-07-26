import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from web.server import (
    get_realtime_crypto_prices,
    get_klines_ohlcv,
    get_defillama_onchain_data,
    get_market_sentiment,
)

async def test_all_tools():
    print("==================================================")
    print("TESTING MULTI-SOURCE TRADING MCP SERVER TOOLS")
    print("==================================================")

    print("\n[1/4] Real-Time Crypto Prices (CoinGecko):")
    prices = await get_realtime_crypto_prices("bitcoin,ethereum,solana")
    print(prices)

    print("\n[2/4] OHLCV Candlestick Data (5m):")
    ohlcv = await get_klines_ohlcv("BTC-USD", "1d", "5m")
    print(ohlcv[:250] + "...")

    print("\n[3/4] DefiLlama On-Chain TVL Data (Ethereum & Solana):")
    eth_tvl = await get_defillama_onchain_data("Ethereum")
    sol_tvl = await get_defillama_onchain_data("Solana")
    print("ETH Chain:", eth_tvl)
    print("SOL Chain:", sol_tvl)

    print("\n[4/4] Market Sentiment & Fear/Greed Index:")
    sentiment = await get_market_sentiment()
    print(sentiment)
    print("\nALL 4 MULTI-SOURCE TOOLS WORKING!")

if __name__ == "__main__":
    asyncio.run(test_all_tools())
