import pandas as pd
import pandas_ta as ta
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    loss = loss.replace(0, np.nan)
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0):
    sma = df["Close"].rolling(period).mean()
    std_dev = df["Close"].rolling(period).std()
    df["BB_Upper"] = sma + (std_dev * std)
    df["BB_Lower"] = sma - (std_dev * std)
    df["BB_SMA"] = sma


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_prev_close = abs(df["High"] - df["Close"].shift(1))
    low_prev_close = abs(df["Low"] - df["Close"].shift(1))
    tr = high_low.combine(high_prev_close, max).combine(low_prev_close, max)
    return tr.rolling(period).mean()


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = df["Close"].ewm(span=fast, adjust=False).mean() - df["Close"].ewm(span=slow, adjust=False).mean()
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    df["MACD"] = macd_line
    df["MACD_Signal"] = signal_line
    df["MACD_Hist"] = histogram


def vwap(df: pd.DataFrame, window: int = 24) -> pd.Series:
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    vol = df["Volume"].replace(0, np.nan).ffill()
    vwap_series = (typical_price * vol).rolling(window, min_periods=5).sum() / vol.rolling(window, min_periods=5).sum()
    return vwap_series.bfill().ffill()


def swing_highs(df: pd.DataFrame, window: int = 3) -> pd.Series:
    highs = df["High"]
    result = pd.Series(False, index=df.index)
    for i in range(window, len(df) - window):
        if all(highs.iloc[i] > highs.iloc[i - j] for j in range(1, window + 1)) and \
           all(highs.iloc[i] > highs.iloc[i + j] for j in range(1, window + 1)):
            result.iloc[i] = True
    return result


def swing_lows(df: pd.DataFrame, window: int = 3) -> pd.Series:
    lows = df["Low"]
    result = pd.Series(False, index=df.index)
    for i in range(window, len(df) - window):
        if all(lows.iloc[i] < lows.iloc[i - j] for j in range(1, window + 1)) and \
           all(lows.iloc[i] < lows.iloc[i + j] for j in range(1, window + 1)):
            result.iloc[i] = True
    return result


def last_swing_points(df: pd.DataFrame, window: int = 3):
    sh = swing_highs(df, window)
    sl = swing_lows(df, window)
    sh_idx = df.index[sh]
    sl_idx = df.index[sl]
    last_sh = sh_idx[-1] if len(sh_idx) > 0 else None
    last_sl = sl_idx[-1] if len(sl_idx) > 0 else None
    return {
        "last_swing_high_price": df.loc[last_sh, "High"] if last_sh is not None else None,
        "last_swing_low_price": df.loc[last_sl, "Low"] if last_sl is not None else None,
        "last_swing_high_time": last_sh,
        "last_swing_low_time": last_sl,
    }


def detect_bos(df: pd.DataFrame, window: int = 10) -> dict:
    recent = df.tail(window)
    price = recent["Close"].iloc[-1]
    high_window = recent.iloc[:-1]["High"].max()
    low_window = recent.iloc[:-1]["Low"].min()

    if pd.isna(high_window) or pd.isna(low_window):
        return {"bullish_bos": False, "bearish_bos": False, "window_high": None, "window_low": None}

    bullish_bos = price > high_window
    bearish_bos = price < low_window

    return {
        "bullish_bos": bool(bullish_bos),
        "bearish_bos": bool(bearish_bos),
        "window_high": float(high_window),
        "window_low": float(low_window),
    }


def order_blocks(df: pd.DataFrame, lookback: int = 30) -> dict:
    bullish_obs = []
    bearish_obs = []
    for i in range(2, min(lookback, len(df))):
        idx = -i
        if df.iloc[idx]["Close"] < df.iloc[idx]["Open"]:
            if df.iloc[idx + 1]["Close"] > df.iloc[idx]["High"]:
                bullish_obs.append({
                    "index": df.index[idx],
                    "high": float(df.iloc[idx]["High"]),
                    "low": float(df.iloc[idx]["Low"]),
                    "strength": "strong" if df.iloc[idx]["Close"] < df.iloc[idx]["Open"] * 0.995 else "normal",
                })
        if df.iloc[idx]["Close"] > df.iloc[idx]["Open"]:
            if df.iloc[idx + 1]["Close"] < df.iloc[idx]["Low"]:
                bearish_obs.append({
                    "index": df.index[idx],
                    "high": float(df.iloc[idx]["High"]),
                    "low": float(df.iloc[idx]["Low"]),
                    "strength": "strong" if df.iloc[idx]["Close"] > df.iloc[idx]["Open"] * 1.005 else "normal",
                })

    current_price = df["Close"].iloc[-1]
    nearest_support = None
    nearest_resistance = None
    for ob in bullish_obs:
        if ob["high"] < current_price:
            if nearest_support is None or ob["high"] > nearest_support:
                nearest_support = ob["high"]
    for ob in bearish_obs:
        if ob["low"] > current_price:
            if nearest_resistance is None or ob["low"] < nearest_resistance:
                nearest_resistance = ob["low"]

    return {
        "bullish_obs": bullish_obs[:5],
        "bearish_obs": bearish_obs[:5],
        "nearest_bullish_ob_high": nearest_support,
        "nearest_bearish_ob_low": nearest_resistance,
    }


def fair_value_gaps(df: pd.DataFrame, lookback: int = 30) -> dict:
    bullish_fvgs = []
    bearish_fvgs = []
    for i in range(2, min(lookback, len(df))):
        idx = -i
        c0_low = df.iloc[idx - 2]["Low"]
        c0_high = df.iloc[idx - 2]["High"]
        c2_low = df.iloc[idx]["Low"]
        c2_high = df.iloc[idx]["High"]

        if c2_low > c0_high:
            gap_top = c2_low
            gap_bottom = c0_high
            bullish_fvgs.append({
                "index": df.index[idx],
                "gap_high": float(gap_top),
                "gap_low": float(gap_bottom),
                "gap_size": float(gap_top - gap_bottom),
            })
        if c2_high < c0_low:
            gap_top = c0_low
            gap_bottom = c2_high
            bearish_fvgs.append({
                "index": df.index[idx],
                "gap_high": float(gap_top),
                "gap_low": float(gap_bottom),
                "gap_size": float(gap_top - gap_bottom),
            })

    current_price = df["Close"].iloc[-1]
    nearest_gap = None
    for fvg in bullish_fvgs:
        if fvg["gap_high"] < current_price:
            if nearest_gap is None or fvg["gap_high"] > nearest_gap:
                nearest_gap = fvg["gap_high"]
    for fvg in bearish_fvgs:
        if fvg["gap_low"] > current_price:
            if nearest_gap is None or fvg["gap_low"] < nearest_gap:
                nearest_gap = fvg["gap_low"]

    return {
        "bullish_fvgs": bullish_fvgs[:3],
        "bearish_fvgs": bearish_fvgs[:3],
        "nearest_fvg_price": nearest_gap,
    }


def volume_spike(df: pd.DataFrame, window: int = 24, multiplier: float = 1.5) -> bool:
    vol_now = df["Volume"].iloc[-1]
    vol_avg = df["Volume"].rolling(window).mean().iloc[-1]
    if vol_avg == 0 or np.isnan(vol_avg):
        return False
    return vol_now > (vol_avg * multiplier)


def btc_steering_filter(df_btc: pd.DataFrame) -> bool:
    df = df_btc.copy()
    df["EMA9"] = ema(df["Close"], 9)
    df["EMA21"] = ema(df["Close"], 21)
    return df["EMA9"].iloc[-1] > df["EMA21"].iloc[-1]


def add_ta_indicators(df: pd.DataFrame):
    df.ta.atr(length=14, append=True)
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df["Vol_24h_Avg"] = df["Volume"].rolling(24).mean()
    df["VWAP"] = vwap(df)


def compute_scoring(
    df_row,
    fng_score: int = 50,
    funding_rate: float = 0.0,
    bos_info: dict = None,
    ob_info: dict = None,
    fvg_info: dict = None,
) -> tuple:
    price = df_row.get("Close", 0)
    ema9 = df_row.get("EMA_9", price)
    ema21 = df_row.get("EMA_21", price)
    ema50 = df_row.get("EMA_50", price)
    rsi_val = df_row.get("RSI_14", 50)
    macd_line = df_row.get("MACD_12_26_9", 0)
    macd_signal = df_row.get("MACDs_12_26_9", 0)
    macd_hist = df_row.get("MACDh_12_26_9", 0)
    vol_now = df_row.get("Volume", 0)
    vol_avg = df_row.get("Vol_24h_Avg", vol_now)
    vwap_val = df_row.get("VWAP", price)
    atr_val = df_row.get("ATRr_14", 0)

    if bos_info is None:
        bos_info = {"bullish_bos": False, "bearish_bos": False}
    if ob_info is None:
        ob_info = {}
    if fvg_info is None:
        fvg_info = {}

    trend_up = ema9 > ema21 > ema50
    trend_down = ema9 < ema21 < ema50

    technical_long = 0
    technical_short = 0

    if trend_up:
        technical_long += 10
    if trend_down:
        technical_short += 10

    if macd_line > macd_signal and macd_hist > 0:
        technical_long += 8
    if macd_line < macd_signal and macd_hist < 0:
        technical_short += 8

    if rsi_val < 35:
        technical_long += 12
    elif rsi_val < 45:
        technical_long += 6
    if rsi_val > 65:
        technical_short += 12
    elif rsi_val > 55:
        technical_short += 6

    pullback_to_ema_long = (price < ema9) and (price >= ema50)
    if pullback_to_ema_long:
        technical_long += 5
    pullback_to_ema_short = (price > ema9) and (price <= ema50)
    if pullback_to_ema_short:
        technical_short += 5

    technical_long = min(technical_long, 40)
    technical_short = min(technical_short, 40)

    vol_spike_flag = vol_now > (vol_avg * 1.5)
    vol_pts = 20 if vol_spike_flag else (8 if vol_now > vol_avg else 0)

    mkt_long = 0
    mkt_short = 0

    price_above_vwap = price > vwap_val
    if price_above_vwap:
        mkt_long += 8
    else:
        mkt_short += 8

    if price_above_vwap and vwap_val > ema50:
        mkt_long += 4
    elif not price_above_vwap and vwap_val < ema50:
        mkt_short += 4

    if bos_info.get("bullish_bos"):
        mkt_long += 8
    if bos_info.get("bearish_bos"):
        mkt_short += 8

    if atr_val > 0 and ob_info:
        ob_support = ob_info.get("nearest_bullish_ob_high")
        ob_resistance = ob_info.get("nearest_bearish_ob_low")
        if ob_support is not None and abs(price - ob_support) < atr_val * 0.5:
            mkt_long += 4
        if ob_resistance is not None and abs(ob_resistance - price) < atr_val * 0.5:
            mkt_short += 4

    if fvg_info:
        nearest_fvg = fvg_info.get("nearest_fvg_price")
        if nearest_fvg is not None and atr_val > 0:
            dist = abs(price - nearest_fvg)
            if dist < atr_val * 0.5:
                if nearest_fvg > price:
                    mkt_short += 4
                else:
                    mkt_long += 4

    mkt_long = min(mkt_long, 20)
    mkt_short = min(mkt_short, 20)

    funding_bullish = funding_rate > 0 and funding_rate < 0.01
    funding_bearish = funding_rate < -0.0001 or funding_rate > 0.015
    derivatives_long = 0
    derivatives_short = 0
    if funding_bullish:
        derivatives_long += 10
    elif funding_bearish:
        derivatives_short += 10
    else:
        derivatives_long += 5
        derivatives_short += 5
    derivatives_long = min(derivatives_long, 20)
    derivatives_short = min(derivatives_short, 20)

    fng_long_pts = 10 if fng_score < 40 else (0 if fng_score > 60 else 5)
    fng_short_pts = 10 if fng_score > 60 else (0 if fng_score < 40 else 5)

    score_long = technical_long + vol_pts + mkt_long + derivatives_long + fng_long_pts
    score_short = technical_short + vol_pts + mkt_short + derivatives_short + fng_short_pts

    score_long = min(score_long, 100)
    score_short = min(score_short, 100)

    return score_long, score_short, trend_up, trend_down


def compute_multi_tf_scoring(
    dataframes: dict[str, pd.DataFrame],
    fng_score: int = 50,
    funding_rate: float = 0.0,
    weights: dict[str, float] = None,
    discount_on_conflict: float = 0.15,
    bonus_on_agreement: float = 0.10,
) -> tuple:
    if weights is None:
        weights = {"1h": 0.50, "4h": 0.30, "1d": 0.20}

    scores = {}
    trend_up_count = 0
    trend_down_count = 0

    for tf, df in dataframes.items():
        if df is None or df.empty or len(df) < 50:
            continue
        df_work = df.copy()
        add_ta_indicators(df_work)
        last = df_work.iloc[-1]

        bos_info = detect_bos(df_work, window=15)
        ob_info = order_blocks(df_work, lookback=30)
        fvg_info = fair_value_gaps(df_work, lookback=30)

        row = last.copy()
        vwap_col = "VWAP"
        row[vwap_col] = last.get(vwap_col, last.get("Close", 0))
        row["Vol_24h_Avg"] = df_work["Vol_24h_Avg"].iloc[-1] if "Vol_24h_Avg" in df_work.columns else last.get("Volume", 0)
        sl, ss, tu, td = compute_scoring(
            row,
            fng_score=fng_score,
            funding_rate=funding_rate,
            bos_info=bos_info,
            ob_info=ob_info,
            fvg_info=fvg_info,
        )
        scores[tf] = (sl, ss, tu, td)
        if tu:
            trend_up_count += 1
        if td:
            trend_down_count += 1

    if not scores:
        return 0, 0, False, False

    weighted_long = 0.0
    weighted_short = 0.0
    total_weight = 0.0

    for tf, (sl, ss, tu, td) in scores.items():
        w = weights.get(tf, 0.2)
        weighted_long += sl * w
        weighted_short += ss * w
        total_weight += w

    if total_weight == 0:
        return 0, 0, False, False

    final_long = weighted_long / total_weight
    final_short = weighted_short / total_weight
    num_tfs = len(scores)
    final_trend_up = trend_up_count > num_tfs / 2
    final_trend_down = trend_down_count > num_tfs / 2

    all_bullish = trend_up_count == num_tfs
    all_bearish = trend_down_count == num_tfs
    all_agree = all_bullish or all_bearish
    has_conflict = (trend_up_count > 0 and trend_down_count > 0)

    if all_agree:
        final_long = min(100, final_long * (1 + bonus_on_agreement))
        final_short = min(100, final_short * (1 + bonus_on_agreement))

    elif has_conflict:
        final_long *= (1 - discount_on_conflict)
        final_short *= (1 - discount_on_conflict)

    final_long = round(min(max(final_long, 0), 100))
    final_short = round(min(max(final_short, 0), 100))

    return final_long, final_short, final_trend_up, final_trend_down
