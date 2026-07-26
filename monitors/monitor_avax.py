import ccxt
import pandas as pd
import sys

sys.path.insert(0, ".")
from indicators import add_ta_indicators, compute_multi_tf_scoring, detect_bos, order_blocks, fair_value_gaps, btc_steering_filter, ema, rsi
from config import SCORING_STRICT_THRESHOLD

ENTRY_PRICE = 6.726
SYMBOL = "AVAX/USDC:USDC"


def _ohlcv_to_df(raw):
    if not raw or len(raw) < 20:
        return None
    df = pd.DataFrame(raw, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df.astype(float)


def check_avax():
    exchange = ccxt.hyperliquid({"enableRateLimit": True, "timeout": 15000})

    dataframes = {}
    for tf, limit in [("1h", 336), ("4h", 126), ("1d", 90)]:
        raw = exchange.fetch_ohlcv(SYMBOL, tf, limit=limit)
        df = _ohlcv_to_df(raw)
        if df is not None and len(df) >= 20:
            dataframes[tf] = df

    ticker = exchange.fetch_ticker(SYMBOL)
    live_price = ticker.get("last", 0)

    fr = 0.005
    try:
        fr_data = exchange.fetch_funding_rate(SYMBOL)
        if fr_data:
            fr = fr_data.get("fundingRate", 0.005)
    except Exception:
        pass

    fng_score = 50
    try:
        import httpx
        r = httpx.get("https://api.alternative.me/fng/", timeout=5)
        fng_score = int(r.json()["data"][0]["value"])
    except Exception:
        pass

    btc_pass = True
    try:
        import yfinance as yf
        df_btc = yf.Ticker("BTC-USD").history(period="3d", interval="1h")
        if not df_btc.empty:
            btc_pass = btc_steering_filter(df_btc)
    except Exception:
        pass

    score_long, score_short, trend_up, trend_down = compute_multi_tf_scoring(
        dataframes, fng_score=fng_score, funding_rate=fr,
    )

    df_1h = dataframes.get("1h")
    if df_1h is not None:
        add_ta_indicators(df_1h)
    last_1h = df_1h.iloc[-1] if df_1h is not None else None
    price = last_1h["Close"] if last_1h is not None else live_price
    atr = last_1h["ATRr_14"] if last_1h is not None else price * 0.02
    vwap_val = last_1h["VWAP"] if last_1h is not None else price
    rsi_val = last_1h["RSI_14"] if last_1h is not None else 50
    macd_hist = last_1h["MACDh_12_26_9"] if last_1h is not None else 0

    vol_now = df_1h["Volume"].iloc[-1] if df_1h is not None else 0
    vol_avg = df_1h["Vol_24h_Avg"].iloc[-1] if df_1h is not None else vol_now
    vol_spike = vol_now > (vol_avg * 1.5) if vol_avg > 0 else False

    bos_info = detect_bos(df_1h, window=15) if df_1h is not None else {}
    ob_info = order_blocks(df_1h, lookback=30) if df_1h is not None else {}
    fvg_info = fair_value_gaps(df_1h, lookback=30) if df_1h is not None else {}

    trend = "BULLISH" if trend_up else "BEARISH" if trend_down else "SIDEWAYS"

    tf_breakdown = []
    for tf in ["1h", "4h", "1d"]:
        if tf in dataframes:
            df_t = dataframes[tf]
            add_ta_indicators(df_t)
            e9 = df_t["EMA_9"].iloc[-1]
            e21 = df_t["EMA_21"].iloc[-1]
            e50 = df_t["EMA_50"].iloc[-1]
            tu = e9 > e21 > e50
            td = e9 < e21 < e50
            t = "BULL" if tu else "BEAR" if td else "SIDE"
            tf_breakdown.append(f"{tf}={t}")

    filled = live_price <= ENTRY_PRICE
    dist_to_entry = ((live_price - ENTRY_PRICE) / ENTRY_PRICE * 100) if not filled else 0

    print(f"\n{'=' * 55}")
    print(f"  AVAX MONITOR — Limit @ ${ENTRY_PRICE}")
    print(f"  MTF Scoring ({', '.join(tf_breakdown)})")
    print(f"{'=' * 55}")
    print(f"  Live Price   : ${live_price:.4f}")
    print(f"  Limit Status : {'✅ FILLED' if filled else '⏳ Menunggu'} (jarak: {dist_to_entry:+.2f}%)")
    print(f"  MTF Score    : {score_long}/100 (threshold: {SCORING_STRICT_THRESHOLD})")
    print(f"  Trend        : {trend}")
    print(f"  RSI 1h       : {rsi_val:.1f}")
    print(f"  VWAP         : {'✅ Above' if price > vwap_val else '❌ Below'}")
    print(f"  Volume Spike : {'✅ YES' if vol_spike else '❌ NO'}")
    print(f"  Funding      : {fr * 100:+.4f}%")
    print(f"  BTC Steering : {'✅ PASS' if btc_pass else '❌ FAIL'}")
    print(f"  F&G          : {fng_score}/100")
    print(f"  OB/FVG       : {'Bullish OB/FVG nearby ✅' if (ob_info.get('nearest_bullish_ob_high') and abs(price - ob_info['nearest_bullish_ob_high']) < atr * 2) or (fvg_info.get('nearest_fvg_price') and abs(price - fvg_info['nearest_fvg_price']) < atr * 2 and fvg_info['nearest_fvg_price'] < price) else 'Tidak dalam range 2× ATR'}")

    valid = score_long >= SCORING_STRICT_THRESHOLD and not trend_down and btc_pass
    print(f"\n  Status Setup : {'🟢 VALID' if valid else '🔴 INVALID'}")
    if not valid:
        reasons = []
        if score_long < SCORING_STRICT_THRESHOLD:
            reasons.append(f"Score turun ({score_long} < {SCORING_STRICT_THRESHOLD})")
        if trend_down:
            reasons.append("Trend berubah bearish")
        if not btc_pass:
            reasons.append("BTC steering filter fail")
        print(f"  Alasan       : {', '.join(reasons)}")

    if filled:
        avg_entry = price
        sl_p = avg_entry - (atr * 1.5)
        tp_p = avg_entry + (atr * 3.0)
        profit_now = (live_price - avg_entry) / avg_entry * 100
        print(f"\n  📋 POSISI TERISI — PnL: {profit_now:+.2f}%")
        print(f"     Avg Entry : ${avg_entry:.4f}")
        print(f"     SL        : ${sl_p:.4f} (-{abs(avg_entry-sl_p)/avg_entry*100:.2f}%)")
        print(f"     TP        : ${tp_p:.4f} (+{abs(tp_p-avg_entry)/avg_entry*100:.2f}%)")
    else:
        e1 = live_price
        e2 = live_price - (atr * 0.8)
        ae = (e1 + e2) / 2
        print(f"\n  📋 SETUP TERTUNDA:")
        print(f"     Entry 1   : ${e1:.4f}")
        print(f"     Entry 2   : ${e2:.4f}")
        print(f"     Avg Entry : ${ae:.4f}")
        print(f"     SL        : ${ae - atr * 1.5:.4f}")
        print(f"     TP        : ${ae + atr * 3.0:.4f}")

    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    check_avax()
