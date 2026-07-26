import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from web.server import (
    get_realtime_crypto_prices,
    get_derivatives_metrics,
    get_orderbook_and_cvd,
    get_liquidation_zones,
    get_whale_alerts,
    get_defillama_onchain_data,
    get_market_sentiment,
)

async def test_pro_suite():
    print("==================================================")
    print("TESTING INSTITUTIONAL PRO TRADING MCP TOOLS")
    print("==================================================")

    print("\n[1] Realtime Price:")
    print(await get_realtime_crypto_prices("bitcoin"))

    print("\n[2] Derivatives (Open Interest & Funding Rate):")
    print(await get_derivatives_metrics("bitcoin"))

    print("\n[3] Orderbook & Cumulative Volume Delta (CVD):")
    print(await get_orderbook_and_cvd("bitcoin"))

    print("\n[4] Liquidation Clusters (Heatmap):")
    print(await get_liquidation_zones(65000.0))

    print("\n[5] Whale Alert Scanner:")
    print(await get_whale_alerts())

    print("\n[6] DefiLlama On-Chain TVL:")
    print(await get_defillama_onchain_data("Ethereum"))

    print("\n[7] Fear & Greed Index:")
    print(await get_market_sentiment())

if __name__ == "__main__":
    asyncio.run(test_pro_suite())
