import time
import httpx
import yfinance as yf
import pandas as pd
from config import ALTCOIN_SYMBOLS, SCORING_STRICT_THRESHOLD
from indicators import (
    add_ta_indicators,
    compute_multi_tf_scoring,
    detect_bos,
    order_blocks,
    fair_value_gaps,
    btc_steering_filter,
)

FEAR_GREED_URL = "https://api.alternative.me/fng/"
COINGECKO_DERIVATIVES_URL = "https://api.coingecko.com/api/v3/derivatives"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


YAHOO_TO_HTX = {
    "BTC-USD": "btcusdt", "ETH-USD": "ethusdt", "BNB-USD": "bnbusdt",
    "SOL-USD": "solusdt", "XRP-USD": "xrpusdt", "ADA-USD": "adausdt",
    "AVAX-USD": "avaxusdt", "DOGE-USD": "dogeusdt", "LINK-USD": "linkusdt",
    "DOT-USD": "dotusdt",
}

YAHOO_TO_COINGECKO = {
    "BTC-USD": "bitcoin", "ETH-USD": "ethereum", "BNB-USD": "binancecoin",
    "SOL-USD": "solana", "XRP-USD": "ripple", "ADA-USD": "cardano",
    "AVAX-USD": "avalanche-2", "DOGE-USD": "dogecoin", "LINK-USD": "chainlink",
    "DOT-USD": "polkadot",
}


_LIVE_PRICE_CACHE: dict[str, tuple[float, float]] = {}


def get_live_price(symbol: str) -> float | None:
    now = time.time()
    cached = _LIVE_PRICE_CACHE.get(symbol)
    if cached and now - cached[0] < 30:
        return cached[1]

    # Try HTX (Huobi) first — real-time, not blocked in Indonesia
    htx_symbol = YAHOO_TO_HTX.get(symbol)
    if htx_symbol:
        try:
            r = httpx.get(
                f"https://api.huobi.pro/market/detail/merged?symbol={htx_symbol}",
                timeout=5, headers=HEADERS
            )
            data = r.json()
            if data.get("status") == "ok":
                price = float(data["tick"]["close"])
                _LIVE_PRICE_CACHE[symbol] = (now, price)
                return price
        except Exception:
            pass

    # Fallback: CoinGecko
    coin_id = YAHOO_TO_COINGECKO.get(symbol)
    if coin_id:
        for attempt in range(3):
            try:
                r = httpx.get(
                    f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd",
                    timeout=5, headers=HEADERS
                )
                data = r.json()
                price = data.get(coin_id, {}).get("usd")
                if price:
                    _LIVE_PRICE_CACHE[symbol] = (now, price)
                    return price
            except Exception:
                if attempt < 2:
                    time.sleep(1)
    return None


def get_fng_score() -> int:
    try:
        r = httpx.get(FEAR_GREED_URL, timeout=5, headers=HEADERS)
        return int(r.json()["data"][0]["value"])
    except Exception:
        return 50


def get_market_funding_rate() -> float:
    try:
        r = httpx.get(COINGECKO_DERIVATIVES_URL, timeout=5, headers=HEADERS)
        data = r.json()[:5]
        rates = [float(d["funding_rate"]) for d in data if d.get("funding_rate") is not None]
        return sum(rates) / len(rates) if rates else 0.005
    except Exception:
        return 0.005




def scan_altcoins():
    print("Analyzing Market Sentiment & Fear/Greed Index...")
    fng_score = get_fng_score()
    print(f"Fear & Greed Score: {fng_score}/100")

    print("Fetching market-wide funding rate...")
    funding_rate = get_market_funding_rate()
    print(f"Avg Funding Rate (top markets): {funding_rate * 100:+.4f}%\n")

    btc = yf.Ticker("BTC-USD")
    df_btc = btc.history(period="7d", interval="1h")
    btc_pass = btc_steering_filter(df_btc)

    print("\n=== BTC STEERING FILTER ===")
    print(f"Status: {'PASS (Bullish)' if btc_pass else 'FAIL (Bearish - High Risk for Altcoins)'}")
    print("===========================\n")

    print("Running Scanner V3.1 (VWAP + OB/FVG + Market Structure)...\n")

    for sym in ALTCOIN_SYMBOLS:
        try:
            ticker = yf.Ticker(sym)
            dfs = {}
            for tf_name, period, interval in [("1h", "14d", "1h"), ("1d", "90d", "1d")]:
                d = ticker.history(period=period, interval=interval)
                if not d.empty and len(d) >= 20:
                    dfs[tf_name] = d

            df_1h = dfs.get("1h")
            if df_1h is None or len(df_1h) < 50:
                continue

            score_long, score_short, trend_up, trend_down = compute_multi_tf_scoring(
                dfs, fng_score=fng_score, funding_rate=funding_rate
            )

            add_ta_indicators(df_1h)
            price = df_1h["Close"].iloc[-1]
            atr = df_1h["ATRr_14"].iloc[-1]
            vwap_val = df_1h["VWAP"].iloc[-1]
            rsi_val = df_1h["RSI_14"].iloc[-1]
            macd_hist = df_1h["MACDh_12_26_9"].iloc[-1]
            ema9 = df_1h["EMA_9"].iloc[-1]
            ema21 = df_1h["EMA_21"].iloc[-1]

            live_price = get_live_price(sym)
            time.sleep(1.5)
            entry_price = live_price if live_price else price
            price_gap = abs(entry_price - price) / price * 100 if live_price else 0
            stale_data = price_gap > 1.0 if live_price else False

            vol_now = df_1h["Volume"].iloc[-1]
            vol_avg = df_1h["Vol_24h_Avg"].iloc[-1] if "Vol_24h_Avg" in df_1h.columns else vol_now
            vol_spike_flag = vol_now > (vol_avg * 1.5)

            bos_info = detect_bos(df_1h, window=15)
            ob_info = order_blocks(df_1h, lookback=30)
            fvg_info = fair_value_gaps(df_1h, lookback=30)

            s_name = sym.replace("-USD", "")

            # Build trend string per TF
            tf_trends = []
            for tf, d in dfs.items():
                add_ta_indicators(d)
                e9 = d["EMA_9"].iloc[-1]; e21 = d["EMA_21"].iloc[-1]; e50 = d["EMA_50"].iloc[-1]
                t = "BULL" if e9 > e21 > e50 else "BEAR" if e9 < e21 < e50 else "SIDE"
                tf_trends.append(f"{tf}={t}")

            print(f"\n{'='*50}")
            print(f"{s_name}")
            print(f"{'='*50}")
            print(f"   Close (yf)  : ${price:.4f}")
            print(f"   Live Price  : ${entry_price:.4f}{' (stale)' if stale_data else ''}")
            if price_gap > 0.1 and live_price:
                print(f"   Gap         : {price_gap:+.2f}%")
            print(f"   Trend       : {'BULLISH' if trend_up else 'BEARISH' if trend_down else 'SIDEWAYS'} ({', '.join(tf_trends)})")
            print(f"   RSI 1h      : {rsi_val:.1f}")
            print(f"   VWAP        : ${vwap_val:.4f} ({'ABOVE' if entry_price > vwap_val else 'BELOW'} VWAP)")
            print(f"   Vol Spike   : {'YES' if vol_spike_flag else 'NO'}")
            print(f"   MACD Hist   : {'+' if macd_hist > 0 else ''}{macd_hist:.2f}")

            bos_str = ""
            if bos_info.get("bullish_bos"):
                bos_str = "BULLISH BOS"
            elif bos_info.get("bearish_bos"):
                bos_str = "BEARISH BOS"
            print(f"   BOS         : {bos_str if bos_str else 'No BOS'}")

            ob_support = ob_info.get("nearest_bullish_ob_high")
            ob_resistance = ob_info.get("nearest_bearish_ob_low")
            ob_str = ""
            if ob_support is not None and abs(entry_price - ob_support) < atr * 2:
                ob_str = f"Bullish OB @ ${ob_support:.4f}"
            if ob_resistance is not None and abs(ob_resistance - entry_price) < atr * 2:
                ob_str += f"{' | ' if ob_str else ''}Bearish OB @ ${ob_resistance:.4f}"
            print(f"   Order Block : {ob_str if ob_str else 'None nearby'}")

            nearest_fvg = fvg_info.get("nearest_fvg_price")
            fvg_str = ""
            if nearest_fvg is not None and abs(entry_price - nearest_fvg) < atr * 2:
                direction = "above" if nearest_fvg > entry_price else "below"
                fvg_str = f"FVG {direction} @ ${nearest_fvg:.4f}"
            print(f"   FVG         : {fvg_str if fvg_str else 'None nearby'}")

            print(f"   Funding     : {funding_rate * 100:+.4f}%")
            print(f"   -----------")
            print(f"   SCORE (MTF) : {score_long}/100 LONG | {score_short}/100 SHORT")

            stale_warn = " (stale data — skip)" if stale_data else ""
            if score_long >= SCORING_STRICT_THRESHOLD and not trend_down and btc_pass and not stale_data:
                print(f"   >>> STRONG LONG SETUP <<<")
                entry_1 = entry_price
                entry_2 = entry_price - (atr * 0.8)
                avg_entry = (entry_1 + entry_2) / 2
                sl = avg_entry - (atr * 1.5)
                tp = avg_entry + (atr * 1.5 * 2)
                print(f"   Setup: Limit Buy ~${avg_entry:.4f} | SL ~${sl:.4f} | TP ~${tp:.4f}")

            if score_short >= SCORING_STRICT_THRESHOLD and not trend_up and not stale_data:
                print(f"   >>> STRONG SHORT SETUP <<<")
                entry_1 = entry_price
                entry_2 = entry_price + (atr * 0.8)
                avg_entry = (entry_1 + entry_2) / 2
                sl = avg_entry + (atr * 1.5)
                tp = avg_entry - (atr * 1.5 * 2)
                print(f"   Setup: Limit Sell ~${avg_entry:.4f} | SL ~${sl:.4f} | TP ~${tp:.4f}")

        except Exception:
            continue


if __name__ == "__main__":
    scan_altcoins()
