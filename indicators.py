import pandas as pd
import numpy as np


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_prev_close = abs(df["High"] - df["Close"].shift(1))
    low_prev_close = abs(df["Low"] - df["Close"].shift(1))
    tr = high_low.combine(high_prev_close, max).combine(low_prev_close, max)
    return tr.rolling(period).mean()


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


def detect_bos(df: pd.DataFrame, window: int = 10) -> dict:
    return detect_structure(df, window)


def _ob_mitigation_ratio(df: pd.DataFrame, ob_idx: int, ob_low: float, ob_high: float) -> dict:
    ob_range = ob_high - ob_low
    if ob_range <= 0:
        return {"mitigated": False, "fully_mitigated": False, "mitigation_ratio": 0.0}
    max_overlap = 0.0
    ob_position = len(df) + ob_idx if ob_idx < 0 else ob_idx
    for _, candle in df.iloc[ob_position + 1:].iterrows():
        candle_low = candle["Low"]
        candle_high = candle["High"]
        overlap_low = max(ob_low, candle_low)
        overlap_high = min(ob_high, candle_high)
        if overlap_high > overlap_low:
            overlap = overlap_high - overlap_low
            if overlap > max_overlap:
                max_overlap = overlap
    ratio = max_overlap / ob_range
    return {
        "mitigated": ratio > 0,
        "fully_mitigated": ratio >= 0.95,
        "mitigation_ratio": round(ratio, 4),
    }


def order_blocks(df: pd.DataFrame, lookback: int = 30) -> dict:
    bullish_obs = []
    bearish_obs = []
    for i in range(2, min(lookback, len(df))):
        idx = -i
        if df.iloc[idx]["Close"] < df.iloc[idx]["Open"]:
            if df.iloc[idx + 1]["Close"] > df.iloc[idx]["High"]:
                ob_high = float(df.iloc[idx]["High"])
                ob_low = float(df.iloc[idx]["Low"])
                mit = _ob_mitigation_ratio(df, idx, ob_low, ob_high)
                bullish_obs.append({
                    "index": df.index[idx],
                    "high": ob_high,
                    "low": ob_low,
                    "strength": "strong" if df.iloc[idx]["Close"] < df.iloc[idx]["Open"] * 0.995 else "normal",
                    **mit,
                })
        if df.iloc[idx]["Close"] > df.iloc[idx]["Open"]:
            if df.iloc[idx + 1]["Close"] < df.iloc[idx]["Low"]:
                ob_high = float(df.iloc[idx]["High"])
                ob_low = float(df.iloc[idx]["Low"])
                mit = _ob_mitigation_ratio(df, idx, ob_low, ob_high)
                bearish_obs.append({
                    "index": df.index[idx],
                    "high": ob_high,
                    "low": ob_low,
                    "strength": "strong" if df.iloc[idx]["Close"] > df.iloc[idx]["Open"] * 1.005 else "normal",
                    **mit,
                })
    current_price = df["Close"].iloc[-1]
    nearest_support = None
    nearest_resistance = None
    for ob in bullish_obs:
        if not ob["fully_mitigated"] and ob["high"] < current_price:
            if nearest_support is None or ob["high"] > nearest_support:
                nearest_support = ob["high"]
    for ob in bearish_obs:
        if not ob["fully_mitigated"] and ob["low"] > current_price:
            if nearest_resistance is None or ob["low"] < nearest_resistance:
                nearest_resistance = ob["low"]
    return {
        "bullish_obs": [ob for ob in bullish_obs if not ob["fully_mitigated"]][:5],
        "bearish_obs": [ob for ob in bearish_obs if not ob["fully_mitigated"]][:5],
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
                "displacement_index": df.index[idx - 1],
                "direction": "long",
                "gap_high": float(gap_top),
                "gap_low": float(gap_bottom),
                "gap_mid": float((gap_top + gap_bottom) / 2),
                "gap_size": float(gap_top - gap_bottom),
            })
        if c2_high < c0_low:
            gap_top = c0_low
            gap_bottom = c2_high
            bearish_fvgs.append({
                "index": df.index[idx],
                "displacement_index": df.index[idx - 1],
                "direction": "short",
                "gap_high": float(gap_top),
                "gap_low": float(gap_bottom),
                "gap_mid": float((gap_top + gap_bottom) / 2),
                "gap_size": float(gap_top - gap_bottom),
            })
    current_price = df["Close"].iloc[-1]
    nearest_bullish_gap_mid = None
    nearest_bullish_gap_high = None
    for fvg in bullish_fvgs:
        if fvg["gap_high"] < current_price:
            if nearest_bullish_gap_high is None or fvg["gap_high"] > nearest_bullish_gap_high:
                nearest_bullish_gap_high = fvg["gap_high"]
                nearest_bullish_gap_mid = fvg["gap_mid"]
    nearest_bearish_gap_mid = None
    nearest_bearish_gap_low = None
    for fvg in bearish_fvgs:
        if fvg["gap_low"] > current_price:
            if nearest_bearish_gap_low is None or fvg["gap_low"] < nearest_bearish_gap_low:
                nearest_bearish_gap_low = fvg["gap_low"]
                nearest_bearish_gap_mid = fvg["gap_mid"]
    return {
        "bullish_fvgs": bullish_fvgs[:3],
        "bearish_fvgs": bearish_fvgs[:3],
        "nearest_fvg_price": nearest_bullish_gap_high if nearest_bullish_gap_high is not None else nearest_bearish_gap_low,
        "nearest_fvg_mid": nearest_bullish_gap_mid if nearest_bullish_gap_mid is not None else nearest_bearish_gap_mid,
        "nearest_bullish_fvg_high": nearest_bullish_gap_high,
        "nearest_bullish_fvg_mid": nearest_bullish_gap_mid,
        "nearest_bearish_fvg_low": nearest_bearish_gap_low,
        "nearest_bearish_fvg_mid": nearest_bearish_gap_mid,
    }


def is_impulsive_candle(row, atr_val=None) -> bool:
    body = abs(row["Close"] - row["Open"])
    full_range = row["High"] - row["Low"]
    if full_range == 0:
        return False
    if body / full_range > 0.5:
        if atr_val is None or body > (atr_val * 0.8):
            return True
    return False


def detect_structure(df: pd.DataFrame, window: int = 15) -> dict:
    if len(df) < window + 5:
        return {
            "bullish_choch": False, "bearish_choch": False,
            "bullish_bos": False, "bearish_bos": False,
            "last_swing_high": None, "last_swing_low": None,
            "event": None,
        }
    atr_vals = atr(df, period=14)
    atr_val = atr_vals.iloc[-1] if not atr_vals.empty else 0
    recent = df.iloc[-window:]
    last_candle = df.iloc[-1]
    sh = swing_highs(df, 3)
    sl = swing_lows(df, 3)
    sh_idx = sh[sh].index[sh[sh].index >= recent.index[0]]
    sl_idx = sl[sl].index[sl[sl].index >= recent.index[0]]
    last_sh_idx = sh_idx[-1] if len(sh_idx) else None
    last_sl_idx = sl_idx[-1] if len(sl_idx) else None
    last_sh = float(df.loc[last_sh_idx, "High"]) if last_sh_idx is not None else float(recent.iloc[:-1]["High"].max())
    last_sl = float(df.loc[last_sl_idx, "Low"]) if last_sl_idx is not None else float(recent.iloc[:-1]["Low"].min())

    bullish_trend = (
        len(sh_idx) >= 2 and len(sl_idx) >= 2
        and df.loc[sh_idx[-1], "High"] > df.loc[sh_idx[-2], "High"]
        and df.loc[sl_idx[-1], "Low"] > df.loc[sl_idx[-2], "Low"]
    )
    bearish_trend = (
        len(sh_idx) >= 2 and len(sl_idx) >= 2
        and df.loc[sh_idx[-1], "High"] < df.loc[sh_idx[-2], "High"]
        and df.loc[sl_idx[-1], "Low"] < df.loc[sl_idx[-2], "Low"]
    )
    bullish_break = last_candle["Close"] > last_sh and is_impulsive_candle(last_candle, atr_val)
    bearish_break = last_candle["Close"] < last_sl and is_impulsive_candle(last_candle, atr_val)
    bullish_choch = bullish_break and bearish_trend
    bearish_choch = bearish_break and bullish_trend
    bullish_bos = bullish_break and not bearish_trend
    bearish_bos = bearish_break and not bullish_trend

    event = None
    if bullish_break:
        event = {
            "direction": "long",
            "kind": "CHOCH" if bullish_choch else "BOS",
            "index": df.index[-1],
            "broken_swing_index": last_sh_idx,
            "level": last_sh,
        }
    elif bearish_break:
        event = {
            "direction": "short",
            "kind": "CHOCH" if bearish_choch else "BOS",
            "index": df.index[-1],
            "broken_swing_index": last_sl_idx,
            "level": last_sl,
        }
    return {
        "bullish_choch": bool(bullish_choch),
        "bearish_choch": bool(bearish_choch),
        "bullish_bos": bool(bullish_bos),
        "bearish_bos": bool(bearish_bos),
        "last_swing_high": last_sh,
        "last_swing_low": last_sl,
        "event": event,
    }


def detect_choch(df: pd.DataFrame, window: int = 15) -> dict:
    return detect_structure(df, window)


def latest_structure_event(df: pd.DataFrame, direction: str, window: int = 15) -> dict:
    """Return the most recent confirmed structure break for one direction."""
    minimum_length = window + 5
    if len(df) < minimum_length:
        return detect_structure(df, window)
    for end in range(len(df), minimum_length - 1, -1):
        result = detect_structure(df.iloc[:end], window)
        event = result["event"]
        if event is not None and event["direction"] == direction:
            return result
    return detect_structure(df, window)


def order_block_for_event(
    df: pd.DataFrame,
    event_index,
    direction: str,
    lookback: int = 30,
) -> dict | None:
    """Return the last opposing candle before the structure displacement."""
    if event_index not in df.index:
        return None
    event_position = df.index.get_loc(event_index)
    first_position = max(0, event_position - lookback)
    for position in range(event_position - 1, first_position - 1, -1):
        candle = df.iloc[position]
        is_opposing = candle["Close"] < candle["Open"] if direction == "long" else candle["Close"] > candle["Open"]
        if not is_opposing:
            continue
        ob_low = float(candle["Low"])
        ob_high = float(candle["High"])
        mitigation = _ob_mitigation_ratio(df, position, ob_low, ob_high)
        return {
            "index": df.index[position],
            "displacement_index": event_index,
            "low": ob_low,
            "high": ob_high,
            **mitigation,
        }
    return None


def liquidity_inflection(df: pd.DataFrame, direction: str = "long", before=None, window: int = 30) -> float | None:
    reference = df.loc[df.index < before] if before is not None else df
    if reference.empty:
        return None
    recent = reference.iloc[-window:]
    if direction == "long":
        return float(recent["Low"].min())
    return float(recent["High"].max())


def volume_spike(df: pd.DataFrame, window: int = 24, multiplier: float = 1.3) -> bool:
    if len(df) < window + 1:
        return False
    vol_now = df["Volume"].iloc[-1]
    vol_avg = df["Volume"].rolling(window).mean().iloc[-1]
    if vol_avg == 0 or np.isnan(vol_avg):
        return False
    return vol_now > (vol_avg * multiplier)


def is_fvg_mitigated(
    df: pd.DataFrame,
    gap_low: float,
    gap_high: float,
    formed_at=None,
) -> bool:
    """Return whether price entered an FVG after the displacement candle formed it."""
    subsequent = df.loc[df.index > formed_at] if formed_at is not None else df
    if subsequent.empty:
        return False
    return bool(((subsequent["High"] >= gap_low) & (subsequent["Low"] <= gap_high)).any())


def is_breakout_candle(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 5,
    vol_multiplier: float = 1.3,
) -> bool:
    if len(df) < lookback + 20:
        return False
    atr_vals = atr(df, period=14)
    atr_val = atr_vals.iloc[-1] if not atr_vals.empty else 0
    last = df.iloc[-1]
    is_impulsive = is_impulsive_candle(last, atr_val)
    has_volume = volume_spike(df, window=24, multiplier=vol_multiplier)
    directional_close = last["Close"] > last["Open"] if direction == "long" else last["Close"] < last["Open"]
    return is_impulsive and has_volume and directional_close


def detect_liquidity_sweep(df: pd.DataFrame, direction: str, before=None, window: int = 15) -> bool:
    """
    Check if a liquidity sweep occurred before the given index.
    A sweep happens when price breaks a previous swing point but then reverses.
    """
    reference = df.loc[df.index < before] if before is not None else df
    if len(reference) < window + 5:
        return False
        
    recent = reference.iloc[-window:]
    
    if direction == "long":
        abs_low = recent["Low"].min()
        abs_low_idx = recent["Low"].idxmin()
        sl = swing_lows(reference, 3)
        sl_idx = sl[sl].index
        valid_sl = sl_idx[sl_idx < abs_low_idx]
        if len(valid_sl) > 0:
            prev_swing_low = float(reference.loc[valid_sl[-1], "Low"])
            if abs_low < prev_swing_low:
                after_sweep = reference.loc[abs_low_idx:]
                if (after_sweep["Close"] > prev_swing_low).any():
                    return True
    else:
        abs_high = recent["High"].max()
        abs_high_idx = recent["High"].idxmax()
        sh = swing_highs(reference, 3)
        sh_idx = sh[sh].index
        valid_sh = sh_idx[sh_idx < abs_high_idx]
        if len(valid_sh) > 0:
            prev_swing_high = float(reference.loc[valid_sh[-1], "High"])
            if abs_high > prev_swing_high:
                after_sweep = reference.loc[abs_high_idx:]
                if (after_sweep["Close"] < prev_swing_high).any():
                    return True
                
    return False
