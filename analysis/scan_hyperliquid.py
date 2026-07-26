import time
import sys
import logging
import ccxt
import pandas as pd
import numpy as np

sys.path.insert(0, ".")
from indicators import (
    add_ta_indicators,
    compute_scoring,
    compute_multi_tf_scoring,
    detect_bos,
    order_blocks,
    fair_value_gaps,
    btc_steering_filter,
)
from config import SCORING_STRICT_THRESHOLD

logger = logging.getLogger(__name__)

HL_SYMBOLS = [
    "BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC",
    "BNB/USDC:USDC", "XRP/USDC:USDC", "ADA/USDC:USDC",
    "AVAX/USDC:USDC", "DOGE/USDC:USDC", "LINK/USDC:USDC",
    "DOT/USDC:USDC", "ARB/USDC:USDC", "OP/USDC:USDC",
    "ATOM/USDC:USDC", "SUI/USDC:USDC", "APT/USDC:USDC",
    "NEAR/USDC:USDC", "INJ/USDC:USDC", "TIA/USDC:USDC",
    "SEI/USDC:USDC", "PEPE/USDC:USDC", "WIF/USDC:USDC",
    "JUP/USDC:USDC", "ONDO/USDC:USDC", "ENA/USDC:USDC",
    "PENDLE/USDC:USDC", "STX/USDC:USDC", "FET/USDC:USDC",
    "AAVE/USDC:USDC", "UNI/USDC:USDC", "LDO/USDC:USDC",
]


def _ohlcv_to_dataframe(raw: list) -> pd.DataFrame | None:
    if not raw or len(raw) < 50:
        return None
    df = pd.DataFrame(raw, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df.astype(float)
    return df


def scan_hyperliquid():
    print("=" * 60)
    print("  HYPERLIQUID SCANNER V1.0 — Perp Market Scan")
    print("=" * 60)

    print("\nFear & Greed...")
    fng_score = 50
    try:
        import httpx
        r = httpx.get("https://api.alternative.me/fng/", timeout=5)
        fng_score = int(r.json()["data"][0]["value"])
    except Exception:
        pass
    print(f"F&G: {fng_score}/100\n")

    print("BTC Steering Filter...")
    btc_pass = True
    try:
        import yfinance as yf
        btc = yf.Ticker("BTC-USD")
        df_btc = btc.history(period="3d", interval="1h")
        if not df_btc.empty:
            btc_pass = btc_steering_filter(df_btc)
    except Exception:
        pass
    print(f"BTC: {'PASS (Bullish)' if btc_pass else 'FAIL (Bearish)'}\n")

    print("Connecting to Hyperliquid...")
    exchange = ccxt.hyperliquid({"enableRateLimit": True, "timeout": 20000})
    all_tickers = exchange.fetch_tickers()
    print(f"Tickers loaded: {len(all_tickers)}\n")

    for sym in HL_SYMBOLS:
        try:
            base = sym.split("/")[0]
            print(f"\n{'=' * 50}")
            print(f"{base}")
            print(f"{'=' * 50}")

            raw_1h = exchange.fetch_ohlcv(sym, "1h", limit=336)
            df_1h = _ohlcv_to_dataframe(raw_1h)
            if df_1h is None:
                print(f"   SKIP — insufficient data")
                continue

            raw_4h = exchange.fetch_ohlcv(sym, "4h", limit=126)
            df_4h = _ohlcv_to_dataframe(raw_4h)

            raw_1d = exchange.fetch_ohlcv(sym, "1d", limit=90)
            df_1d = _ohlcv_to_dataframe(raw_1d)

            dataframes = {"1h": df_1h}
            if df_4h is not None and len(df_4h) >= 20:
                dataframes["4h"] = df_4h
            if df_1d is not None and len(df_1d) >= 20:
                dataframes["1d"] = df_1d

            funding_rate = 0.005
            try:
                fr = exchange.fetch_funding_rate(sym)
                if fr and fr.get("fundingRate") is not None:
                    funding_rate = fr["fundingRate"]
            except Exception:
                pass

            score_long, score_short, trend_up, trend_down = compute_multi_tf_scoring(
                dataframes,
                fng_score=fng_score,
                funding_rate=funding_rate,
            )

            add_ta_indicators(df_1h)
            last = df_1h.iloc[-1]
            price = last["Close"]
            atr = last["ATRr_14"]
            vwap_val = last["VWAP"]
            ema9 = last["EMA_9"]
            ema21 = last["EMA_21"]
            rsi_val = last["RSI_14"]
            macd_hist = last["MACDh_12_26_9"]

            ticker_data = all_tickers.get(sym, {})
            live_price = ticker_data.get("last") or price
            hl_vol = ticker_data.get("quoteVolume", 0) or 0

            vol_now = df_1h["Volume"].iloc[-1]
            vol_avg = df_1h["Vol_24h_Avg"].iloc[-1]
            vol_spike_flag = vol_now > (vol_avg * 1.5) if vol_avg > 0 else False

            bos_info = detect_bos(df_1h, window=15)
            ob_info = order_blocks(df_1h, lookback=30)
            fvg_info = fair_value_gaps(df_1h, lookback=30)

            tf_breakdown = []
            for tf_name, df_tf in dataframes.items():
                add_ta_indicators(df_tf)
                ema9_tf = df_tf["EMA_9"].iloc[-1]
                ema21_tf = df_tf["EMA_21"].iloc[-1]
                ema50_tf = df_tf["EMA_50"].iloc[-1]
                tu_tf = ema9_tf > ema21_tf > ema50_tf
                td_tf = ema9_tf < ema21_tf < ema50_tf
                trend_tf = "BULLISH" if tu_tf else "BEARISH" if td_tf else "SIDE"
                tf_breakdown.append(f"{tf_name}={trend_tf}")

            print(f"   HL Price    : ${live_price:.4f}")
            print(f"   Trend       : {'BULLISH' if trend_up else 'BEARISH' if trend_down else 'SIDEWAYS'} ({', '.join(tf_breakdown)})")
            print(f"   RSI 1h      : {rsi_val:.1f}")
            print(f"   VWAP        : ${vwap_val:.4f} ({'ABOVE' if live_price > vwap_val else 'BELOW'} VWAP)")
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
            if ob_support is not None and abs(live_price - ob_support) < atr * 2:
                ob_str = f"Bullish OB @ ${ob_support:.4f}"
            if ob_resistance is not None and abs(ob_resistance - live_price) < atr * 2:
                ob_str += f"{' | ' if ob_str else ''}Bearish OB @ ${ob_resistance:.4f}"
            print(f"   Order Block : {ob_str if ob_str else 'None nearby'}")

            nearest_fvg = fvg_info.get("nearest_fvg_price")
            fvg_str = ""
            if nearest_fvg is not None and abs(live_price - nearest_fvg) < atr * 2:
                direction = "above" if nearest_fvg > live_price else "below"
                fvg_str = f"FVG {direction} @ ${nearest_fvg:.4f}"
            print(f"   FVG         : {fvg_str if fvg_str else 'None nearby'}")

            fr_pct = funding_rate * 100
            fr_note = ""
            if funding_rate > 0.015:
                fr_note = " (HIGH — caution short)"
            elif funding_rate > 0.01:
                fr_note = " (elevated)"
            elif funding_rate < 0:
                fr_note = " (negative — bullish)"
            print(f"   Funding     : {fr_pct:+.4f}%{fr_note}")
            print(f"   HL Vol 24h  : ${hl_vol:,.0f}")
            print(f"   -----------")
            print(f"   SCORE (MTF) : {score_long}/100 LONG | {score_short}/100 SHORT")

            if score_long >= SCORING_STRICT_THRESHOLD and not trend_down and btc_pass:
                print(f"   >>> STRONG LONG SETUP <<<")
                entry_1 = live_price
                entry_2 = live_price - (atr * 0.8)
                avg_entry = (entry_1 + entry_2) / 2
                sl = avg_entry - (atr * 1.5)
                tp = avg_entry + (atr * 3.0)
                print(f"   Entry: ~${avg_entry:.4f} | SL ~${sl:.4f} | TP ~${tp:.4f} (1:2)")

            if score_short >= SCORING_STRICT_THRESHOLD and not trend_up:
                print(f"   >>> STRONG SHORT SETUP <<<")
                entry_1 = live_price
                entry_2 = live_price + (atr * 0.8)
                avg_entry = (entry_1 + entry_2) / 2
                sl = avg_entry + (atr * 1.5)
                tp = avg_entry - (atr * 3.0)
                print(f"   Entry: ~${avg_entry:.4f} | SL ~${sl:.4f} | TP ~${tp:.4f} (1:2)")

        except Exception as e:
            print(f"   ERROR: {e}")
            continue


if __name__ == "__main__":
    scan_hyperliquid()
