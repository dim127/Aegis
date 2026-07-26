import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from web.server import get_binance_klines, get_defillama_onchain_data, get_market_sentiment

async def test_all():
    print("=== TESTING 1: BINANCE API (SPOT & FUTURES) ===")
    binance_res = await get_binance_klines("BTCUSDT", "5m", 3, futures=True)
    print("Binance Futures Output (First 200 chars):", binance_res[:200])

    binance_spot_res = await get_binance_klines("BTCUSDT", "5m", 3, futures=False)
    print("Binance Spot Output (First 200 chars):", binance_spot_res[:200])

    print("\n=== TESTING 2: DEFILLAMA ON-CHAIN API ===")
    defillama_res = await get_defillama_onchain_data("Ethereum")
    print("DefiLlama Output:", defillama_res)

    print("\n=== TESTING 3: MARKET SENTIMENT & FEAR/GREED API ===")
    sentiment_res = await get_market_sentiment()
    print("Sentiment Output:", sentiment_res)

if __name__ == "__main__":
    asyncio.run(test_all())
