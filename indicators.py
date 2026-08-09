import pandas as pd
import numpy as np


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = (df["High"] - df["Low"]).to_numpy()
    high_prev_close = (df["High"] - df["Close"].shift(1)).abs().to_numpy()
    low_prev_close = (df["Low"] - df["Close"].shift(1)).abs().to_numpy()
    tr = pd.Series(
        np.maximum(np.maximum(high_low, high_prev_close), low_prev_close),
        index=df.index,
    )
    return tr.rolling(period).mean()


def swing_highs(df: pd.DataFrame, window: int = 3) -> pd.Series:
    highs = df["High"].to_numpy()
    n = len(highs)
    result = np.zeros(n, dtype=bool)
    lo, hi = window, n - window
    if hi > lo:
        center = highs[lo:hi]
        left = np.column_stack([highs[lo - j:hi - j] for j in range(1, window + 1)])
        right = np.column_stack([highs[lo + j:hi + j] for j in range(1, window + 1)])
        result[lo:hi] = (center[:, None] > left).all(axis=1) & (center[:, None] > right).all(axis=1)
    return pd.Series(result, index=df.index)


def swing_lows(df: pd.DataFrame, window: int = 3) -> pd.Series:
    lows = df["Low"].to_numpy()
    n = len(lows)
    result = np.zeros(n, dtype=bool)
    lo, hi = window, n - window
    if hi > lo:
        center = lows[lo:hi]
        left = np.column_stack([lows[lo - j:hi - j] for j in range(1, window + 1)])
        right = np.column_stack([lows[lo + j:hi + j] for j in range(1, window + 1)])
        result[lo:hi] = (center[:, None] < left).all(axis=1) & (center[:, None] < right).all(axis=1)
    return pd.Series(result, index=df.index)


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


def fair_value_gaps(df: pd.DataFrame, lookback: int = 30, max_fvgs: int | None = None) -> dict:
    """Find 3-candle fair value gaps within `lookback` bars.

    `max_fvgs` caps how many are returned, newest first. It used to be hardcoded
    to 3, which silently made the caller's `lookback=60` meaningless: the
    strategy sorts the returned gaps to pick the one nearest price, but was only
    ever choosing among the 3 most recent. Default None returns everything found
    in the lookback, so the caller's window means what it says.
    """
    bullish_fvgs = []
    bearish_fvgs = []
    for i in range(2, min(lookback, len(df) - 1)):
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
        "bullish_fvgs": bullish_fvgs[:max_fvgs] if max_fvgs else bullish_fvgs,
        "bearish_fvgs": bearish_fvgs[:max_fvgs] if max_fvgs else bearish_fvgs,
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


def _swings_for_prefix(full_high: pd.Series, full_low: pd.Series, end: int, window: int):
    """Swing flags for df[:end], derived from the full-frame computation.

    A fractal swing at position i needs `window` bars on either side, and
    swing_highs only scans range(window, n - window). So within a prefix of
    length `end`, position i is marked exactly when the full frame marks it AND
    i <= end - 1 - window. Everything nearer the cut is unconfirmable there.

    That equivalence is what lets the backward search compute swings once
    instead of once per candidate, and it is asserted directly in
    tests/test_structure_perf.py rather than assumed.
    """
    cutoff = end - 1 - window
    index = full_high.index[:end]
    high = np.array(full_high.to_numpy()[:end], dtype=bool)
    low = np.array(full_low.to_numpy()[:end], dtype=bool)
    keep = max(cutoff + 1, 0)
    high[keep:] = False
    low[keep:] = False
    return pd.Series(high, index=index), pd.Series(low, index=index)


def detect_structure(df: pd.DataFrame, window: int = 15, trend_window: int | None = None,
                     swings: tuple | None = None, atr_value: float | None = None) -> dict:
    """Classify the last candle's break of recent structure.

    Two different lookbacks are needed and conflating them was a real defect:

    * `window` bounds which swing counts as *the level being broken*. It should
      stay short, because breaking a stale high is not a structure event.
    * `trend_window` bounds the swing sequence used to decide whether a trend
      exists at all. Two confirmed swings per side simply do not fit in 15 bars
      — measured on BTC 4h, a trend was detectable in only 13.8% of bars at
      window=15, versus ~43% at 30-40. With no trend detectable, every break
      was classified trendless and the CHoCH/BOS distinction never fired.
    """
    trend_window = trend_window if trend_window is not None else window * 2
    if len(df) < window + 5:
        return {
            "bullish_choch": False, "bearish_choch": False,
            "bullish_bos": False, "bearish_bos": False,
            "last_swing_high": None, "last_swing_low": None,
            "event": None,
        }
    # Only the final ATR reading is used. Recomputing the whole rolling mean per
    # candidate was a quarter of this function's runtime; a backward scan can
    # pass the value in. Rolling mean at position i depends only on i-13..i, so
    # the prefix value equals the full-frame value there — exact, not an
    # approximation.
    if atr_value is not None:
        atr_val = atr_value
    else:
        atr_vals = atr(df, period=14)
        atr_val = atr_vals.iloc[-1] if not atr_vals.empty else 0
    recent = df.iloc[-window:]
    last_candle = df.iloc[-1]
    # `swings` lets a caller hand in an already-computed pair for this exact
    # frame, so a backward search does not recompute them per candidate.
    if swings is not None:
        sh, sl = swings
    else:
        sh = swing_highs(df, 3)
        sl = swing_lows(df, 3)
    # Positional numpy rather than pandas boolean masking. The mask-then-compare
    # pattern ran four times per call and dominated the remaining runtime in
    # check_array_indexer; positions give the same answers without the dtype
    # dispatch on every lookup.
    n = len(df)
    highs = df["High"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    sh_pos = np.flatnonzero(sh.to_numpy())
    sl_pos = np.flatnonzero(sl.to_numpy())

    recent_start = n - min(window, n)
    sh_recent = sh_pos[sh_pos >= recent_start]
    sl_recent = sl_pos[sl_pos >= recent_start]
    last_sh_idx = df.index[sh_recent[-1]] if len(sh_recent) else None
    last_sl_idx = df.index[sl_recent[-1]] if len(sl_recent) else None
    last_sh = (float(highs[sh_recent[-1]]) if len(sh_recent)
               else float(recent.iloc[:-1]["High"].max()))
    last_sl = (float(lows[sl_recent[-1]]) if len(sl_recent)
               else float(recent.iloc[:-1]["Low"].min()))

    # Trend context comes from the wider window; the break level above does not.
    trend_start = n - min(trend_window, n)
    t_sh = sh_pos[sh_pos >= trend_start]
    t_sl = sl_pos[sl_pos >= trend_start]
    has_two = len(t_sh) >= 2 and len(t_sl) >= 2
    bullish_trend = (
        has_two
        and highs[t_sh[-1]] > highs[t_sh[-2]]
        and lows[t_sl[-1]] > lows[t_sl[-2]]
    )
    bearish_trend = (
        has_two
        and highs[t_sh[-1]] < highs[t_sh[-2]]
        and lows[t_sl[-1]] < lows[t_sl[-2]]
    )
    bullish_break = last_candle["Close"] > last_sh and is_impulsive_candle(last_candle, atr_val)
    bearish_break = last_candle["Close"] < last_sl and is_impulsive_candle(last_candle, atr_val)
    # BOS is continuation, so it requires the trend it continues; CHoCH is
    # reversal, so it requires the opposite trend to reverse. A break with no
    # established trend (fewer than two confirmed swings each side) is neither —
    # it is just an impulsive candle clearing a recent extreme.
    #
    # The old code called that third case a BOS, which made 97% of signals
    # "BOS" and hid how weak the structure gate really was. The classification
    # below is descriptive only: `bullish_break` / `bearish_break` stay the
    # gating flags, so entry behaviour is unchanged and the three kinds can now
    # be measured separately before any of them is filtered out.
    bullish_choch = bullish_break and bearish_trend
    bearish_choch = bearish_break and bullish_trend
    bullish_bos = bullish_break and bullish_trend
    bearish_bos = bearish_break and bearish_trend
    trendless = not (bullish_trend or bearish_trend)

    event = None
    if bullish_break:
        event = {
            "direction": "long",
            "kind": "CHOCH" if bullish_choch else ("BOS" if bullish_bos else "BREAK"),
            "index": df.index[-1],
            "broken_swing_index": last_sh_idx,
            "level": last_sh,
        }
    elif bearish_break:
        event = {
            "direction": "short",
            "kind": "CHOCH" if bearish_choch else ("BOS" if bearish_bos else "BREAK"),
            "index": df.index[-1],
            "broken_swing_index": last_sl_idx,
            "level": last_sl,
        }
    return {
        "bullish_choch": bool(bullish_choch),
        "bearish_choch": bool(bearish_choch),
        "bullish_bos": bool(bullish_bos),
        "bearish_bos": bool(bearish_bos),
        "bullish_break": bool(bullish_break),
        "bearish_break": bool(bearish_break),
        "trendless_break": bool((bullish_break or bearish_break) and trendless),
        "last_swing_high": last_sh,
        "last_swing_low": last_sl,
        "event": event,
    }


def detect_choch(df: pd.DataFrame, window: int = 15) -> dict:
    return detect_structure(df, window)


def latest_structure_event(
    df: pd.DataFrame,
    direction: str,
    window: int = 15,
    max_bars_back: int = 30,
) -> dict:
    """Return the most recent confirmed structure break for one direction.

    `max_bars_back` bounds how far back the break may have happened. Without it
    the search ran to the start of the frame, so with 100 HTF candles a 4h break
    from over two weeks ago could still satisfy the structure gate on a live
    entry. A structure event that old is not context, it is history.
    """
    minimum_length = window + 5
    if len(df) < minimum_length:
        return detect_structure(df, window)
    earliest = max(minimum_length - 1, len(df) - max_bars_back)
    # Swings are a property of the frame, not of where the search happens to be
    # looking, so compute them once and derive each prefix from them. Recomputing
    # per candidate meant up to 30 full fractal passes and 30 rounds of pandas
    # boolean indexing for a single call.
    full_high = swing_highs(df, 3)
    full_low = swing_lows(df, 3)
    full_atr = atr(df, period=14).to_numpy()
    for end in range(len(df), earliest, -1):
        result = detect_structure(
            df.iloc[:end], window,
            swings=_swings_for_prefix(full_high, full_low, end, 3),
            atr_value=float(full_atr[end - 1]),
        )
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


def liquidity_inflection(
    df: pd.DataFrame,
    direction: str = "long",
    before=None,
    window: int = 30,
    swing_window: int = 3,
) -> float | None:
    """Stop-loss anchor: the last confirmed swing before `before`.

    The rolling extreme of the whole window is not a structural level — it is
    just the furthest price travelled, so it sits far from the entry and
    inflates R. With R inflated, a 3R target is a move the setup rarely makes
    (measured: median MFE 0.66R, only 14% of trades reached 3R). The last
    confirmed swing is the level price actually reacted to, and it keeps R
    proportional to the structure being traded.

    Falls back to the rolling extreme when no swing is confirmed in the window:
    a fractal swing needs `swing_window` bars on each side, so short or very
    quiet frames can legitimately contain none.
    """
    reference = df.loc[df.index < before] if before is not None else df
    if reference.empty:
        return None
    recent = reference.iloc[-window:]

    if direction == "long":
        swings = swing_lows(reference, swing_window)
        confirmed = swings[swings].index
        in_window = confirmed[confirmed >= recent.index[0]]
        if len(in_window):
            return float(reference.loc[in_window[-1], "Low"])
        return float(recent["Low"].min())

    swings = swing_highs(reference, swing_window)
    confirmed = swings[swings].index
    in_window = confirmed[confirmed >= recent.index[0]]
    if len(in_window):
        return float(reference.loc[in_window[-1], "High"])
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
