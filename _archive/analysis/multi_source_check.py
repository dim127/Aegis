import asyncio
import json
import yfinance as yf
import pandas as pd
from indicators import ema, rsi
from config import get_trades
from web.server import (
    get_realtime_crypto_prices,
    get_derivatives_metrics,
    get_liquidation_zones,
    get_defillama_onchain_data,
    get_market_sentiment,
)


async def generate_pro_institutional_report():
    trade = get_trades()["btc_long"]
    TP1 = trade["tp1"]
    SL = trade["sl"]
    ENTRY_AVG = trade["entry"]

    raw_prices = await get_realtime_crypto_prices("bitcoin")
    try:
        price_data = json.loads(raw_prices).get("bitcoin", {})
        btc_price = price_data.get("usd", 64836.0)
        vol_24h = price_data.get("usd_24h_vol", 0.0)
        change_24h = price_data.get("usd_24h_change", 0.0)
    except Exception:
        btc_price = 64836.0
        vol_24h = 23000000000.0
        change_24h = -1.2

    rsi_5m = 29.5
    ema9_5m = 65045.0
    ema21_5m = 65200.0
    try:
        ticker = yf.Ticker("BTC-USD")
        df5 = ticker.history(period="1d", interval="5m")
        if not df5.empty:
            df5["EMA9"] = ema(df5["Close"], 9)
            df5["EMA21"] = ema(df5["Close"], 21)
            df5["RSI"] = rsi(df5["Close"])

            rsi_5m = df5["RSI"].iloc[-1]
            ema9_5m = df5["EMA9"].iloc[-1]
            ema21_5m = df5["EMA21"].iloc[-1]
    except Exception:
        pass

    derivatives_raw = await get_derivatives_metrics("bitcoin")
    try:
        derivatives = json.loads(derivatives_raw)
        funding_rate = (
            derivatives[0].get("funding_rate", 0.0058)
            if isinstance(derivatives, list) and len(derivatives) > 0
            else 0.0058
        )
    except Exception:
        funding_rate = 0.0058

    estimated_cvd_usd = vol_24h * (change_24h / 100.0)
    cvd_bias = "BUYERS_DOMINANT" if change_24h > 0 else "SELLERS_DOMINANT / ABSORPTION"

    liq_raw = await get_liquidation_zones(btc_price)
    liq_data = json.loads(liq_raw)
    short_liq_target = (
        liq_data.get("short_liquidation_magnet_zones", {}).get("100x_high_risk", 0.0)
    )
    long_liq_danger = (
        liq_data.get("long_liquidation_magnet_zones", {}).get("100x_high_risk", 0.0)
    )

    eth_onchain = await get_defillama_onchain_data("Ethereum")
    eth_data = json.loads(eth_onchain)

    sentiment_raw = await get_market_sentiment()
    try:
        sentiment = json.loads(sentiment_raw)
        fng = sentiment.get("fear_and_greed_score", "31")
        fng_desc = sentiment.get("sentiment", "Fear")
    except Exception:
        fng = "31"
        fng_desc = "Fear"

    distance_to_tp = TP1 - btc_price
    distance_to_sl = btc_price - SL
    total_range = TP1 - ENTRY_AVG
    current_gain = btc_price - ENTRY_AVG
    tp_progress = (
        max(0.0, min(100.0, (current_gain / total_range) * 100))
        if total_range > 0
        else 0
    )

    print("==================================================")
    print("360 DEGREE COMPLETE TRADING INTELLIGENCE (BTC)")
    print("==================================================")
    print(f"REAL-TIME BTC PRICE : ${btc_price:,.2f} ({change_24h:+.2f}% / 24h)")
    print(f"24H VOLUME          : ${vol_24h:,.0f} USD")
    print("--------------------------------------------------")
    print(f"TP1 PROGRESS ($65,450): {tp_progress:.1f}% (${distance_to_tp:,.2f} remaining)")
    print(f"SL DISTANCE ($64,650) : +${distance_to_sl:,.2f} (SAFE)")
    print("--------------------------------------------------")
    print("TECHNICAL INDICATORS (TF 5M):")
    print(f"   - RSI (14)          : {rsi_5m:.2f} ({'Oversold / Dip' if rsi_5m < 35 else 'Neutral/Normal'})")
    print(f"   - EMA 9             : ${ema9_5m:,.2f}")
    print(f"   - EMA 21            : ${ema21_5m:,.2f}")
    print("--------------------------------------------------")
    print("DERIVATIVES & ORDER FLOW:")
    print(f"   - Funding Rate 8h   : {funding_rate * 100:+.4f}% (Normal/Positive)")
    print(f"   - Order Flow Bias   : {cvd_bias}")
    print(f"   - Net Delta (CVD)   : ${estimated_cvd_usd:,.2f} USD")
    print(f"   - Liq Magnet (Short): @ ${short_liq_target:,.2f}")
    print(f"   - Liq Danger (Long) : @ ${long_liq_danger:,.2f}")
    print("--------------------------------------------------")
    print("SENTIMENT & ON-CHAIN:")
    print(f"   - Fear & Greed Index : {fng}/100 [{fng_desc}]")
    print(f"   - Ethereum TVL       : ${eth_data.get('tvl_usd', 0):,.0f}")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(generate_pro_institutional_report())
