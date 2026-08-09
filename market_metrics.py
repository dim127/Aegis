"""Market positioning metrics for Aegis.

- Binance 24h Long/Short account ratio (fapi public endpoint, no API key).
- Liquidation cluster estimate from the local OHLCV volume profile.

The long/short data is network based, so it is cached in SQLite with a TTL
(poll_scanner spawns a fresh process for every scan). The cluster estimate is
a pure function of OHLCV and works offline (also in backtests).
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd
import requests

import db

logger = logging.getLogger(__name__)

FAPI_DATA = "https://fapi.binance.com/futures/data"
FAPI_TIMEOUT = 15

# Which crowd to measure. The default is deliberately the position-weighted top
# traders, not the global account count: the global endpoint weights every
# retail account equally, so it answers "how many people are long" rather than
# "how much size is long". The two disagree materially — sampled together on
# BTC, global accounts read 55.2% long while top-trader positions read 61.4%.
LONG_SHORT_SOURCES = {
    "top_position": "topLongShortPositionRatio",
    "top_account": "topLongShortAccountRatio",
    "global_account": "globalLongShortAccountRatio",
}
DEFAULT_LONG_SHORT_SOURCE = "top_position"


def symbol_to_binance(symbol: str) -> str:
    """Map a unified pair like BTC/USDT:USDT to the Binance symbol BTCUSDT."""
    return symbol.replace("/", "").split(":")[0]


def _resolve_source(source: str | None) -> tuple[str, str]:
    key = source or DEFAULT_LONG_SHORT_SOURCE
    if key not in LONG_SHORT_SOURCES:
        logger.warning(f"Unknown long_short_source '{key}', using {DEFAULT_LONG_SHORT_SOURCE}")
        key = DEFAULT_LONG_SHORT_SOURCE
    return key, LONG_SHORT_SOURCES[key]


def fetch_global_long_short(
    symbol: str, period: str = "1h", limit: int = 25, source: str | None = None
) -> Optional[list]:
    _, endpoint = _resolve_source(source)
    try:
        response = requests.get(
            f"{FAPI_DATA}/{endpoint}",
            params={
                "symbol": symbol_to_binance(symbol),
                "period": period,
                "limit": limit,
            },
            timeout=FAPI_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Long/short ratio fetch failed for {symbol}: {e}")
        return None


def _summarise_long_short(data: list) -> dict:
    longs = np.array([float(row["longAccount"]) for row in data])
    long_pct = float(np.mean(longs) * 100.0)
    return {
        "long_pct": round(long_pct, 1),
        "short_pct": round(100.0 - long_pct, 1),
        "ratio": round(float(np.mean([float(row["longShortRatio"]) for row in data])), 3),
        "bias": "long" if long_pct > 50.0 else "short",
    }


def long_short_24h(symbol: str, cache_minutes: int = 60, source: str | None = None) -> Optional[dict]:
    """Average Binance long/short ratio over the last 24h.

    Returns e.g. {"long_pct": 53.4, "short_pct": 46.6, "ratio": 1.15, "bias": "long"}.
    """
    key, _ = _resolve_source(source)
    metric = f"long_short_24h_{key}"
    cached = db.get_market_metric(symbol, metric, cache_minutes)
    if cached is not None:
        return cached
    data = fetch_global_long_short(symbol, source=key)
    if not data:
        return None
    result = _summarise_long_short(data)
    db.set_market_metric(symbol, metric, result)
    return result


def download_long_short_history(
    symbol: str, period: str = "1h", limit: int = 500, source: str | None = None
) -> int:
    """Persist the long/short series so a backtest can replay it.

    This is why the backtest could never score factor 7: the replay hardcoded
    None on the assumption no history existed. It does — Binance serves roughly
    30 days on these endpoints.
    """
    key, _ = _resolve_source(source)
    data = fetch_global_long_short(symbol, period=period, limit=limit, source=key)
    if not data:
        return 0
    rows = [
        {"timestamp": int(row["timestamp"]), "value": float(row["longAccount"]) * 100.0,
         "extra": {"ratio": float(row["longShortRatio"])}}
        for row in data
    ]
    return db.save_positioning_history(symbol, f"long_short_{key}", period, rows)


def download_open_interest_history(symbol: str, period: str = "4h", limit: int = 500) -> int:
    """Persist the open interest series.

    Resolution and history trade off against each other on this endpoint:
    5m reaches back ~1.7 days, 15m ~5, 1h ~21, and only 4h covers a full ~31
    days. A liquidity sweep on a 15m chart resolves in a handful of candles, so
    4h open interest cannot confirm one specific sweep — at this resolution it
    is a *regime* measure (is open interest building or unwinding), and that is
    how the strategy consumes it. Anything finer would be unbacktestable, which
    is the exact trap factor 7 was stuck in.
    """
    try:
        response = requests.get(
            f"{FAPI_DATA}/openInterestHist",
            params={"symbol": symbol_to_binance(symbol), "period": period, "limit": limit},
            timeout=FAPI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Open interest fetch failed for {symbol}: {e}")
        return 0
    if not data:
        return 0
    rows = [
        {"timestamp": int(row["timestamp"]), "value": float(row["sumOpenInterest"]),
         "extra": {"notional": float(row.get("sumOpenInterestValue", 0.0))}}
        for row in data
    ]
    return db.save_positioning_history(symbol, "open_interest", period, rows)


def download_funding_history(symbol: str, limit: int = 1000) -> int:
    """Persist the funding rate series.

    Funding is the only positioning series with real depth: the endpoint serves
    ~166 days at an 8-hour cadence, versus ~30 days for the futures/data
    endpoints. That matters because 30 days is a single market regime, and a
    factor that only ever gets tested inside one regime cannot be trusted.
    """
    try:
        response = requests.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": symbol_to_binance(symbol), "limit": limit},
            timeout=FAPI_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Funding rate fetch failed for {symbol}: {e}")
        return 0
    if not data:
        return 0
    rows = [
        # Stored in basis points: raw funding is ~1e-5 and rounds badly.
        {"timestamp": int(row["fundingTime"]), "value": float(row["fundingRate"]) * 10_000.0}
        for row in data
    ]
    return db.save_positioning_history(symbol, "funding_rate", "8h", rows)


class PositioningSeries:
    """As-of lookup over a positioning series (no lookahead).

    Returns the most recent observation at or before the requested time, so a
    replay never sees a ratio that was published after the candle it is scoring.
    """

    def __init__(self, symbol: str, metric: str, period: str):
        rows = db.load_positioning_history(symbol, metric, period)
        self.times = np.array([r[0] for r in rows], dtype=np.int64)
        self.values = np.array([r[1] for r in rows], dtype=float)

    def __len__(self) -> int:
        return len(self.times)

    def as_of(self, when_ms: int) -> Optional[float]:
        if len(self.times) == 0:
            return None
        pos = int(np.searchsorted(self.times, when_ms, side="right")) - 1
        if pos < 0:
            return None
        return float(self.values[pos])

    def context_as_of(self, when_ms: int) -> Optional[dict]:
        long_pct = self.as_of(when_ms)
        if long_pct is None:
            return None
        return {
            "long_pct": round(long_pct, 1),
            "short_pct": round(100.0 - long_pct, 1),
            "ratio": round(long_pct / max(100.0 - long_pct, 1e-9), 3),
            "bias": "long" if long_pct > 50.0 else "short",
        }

    def zscore_as_of(self, when_ms: int, lookback: int = 60) -> Optional[float]:
        """How unusual the current reading is versus its own recent history.

        Absolute levels are not comparable across pairs — each has its own
        baseline funding — so a fixed threshold measures the pair, not the
        signal. This is the mistake that made factor 7 useless: it compared an
        always-above-50% series against a fixed 50% line, so it never once fired
        for a long across 1309 observations.
        """
        pos = int(np.searchsorted(self.times, when_ms, side="right")) - 1
        if pos < 0:
            return None
        window = self.values[max(0, pos - lookback + 1): pos + 1]
        if len(window) < 10:
            return None
        std = window.std()
        if std == 0:
            return None
        return float((self.values[pos] - window.mean()) / std)

    def change_pct(self, when_ms: int, lookback_ms: int) -> Optional[float]:
        """Percent change between the observation `lookback_ms` earlier and now.

        Both endpoints are as-of lookups, so this never reads a value published
        after `when_ms`. Returns None when either side is missing.
        """
        now = self.as_of(when_ms)
        then = self.as_of(when_ms - lookback_ms)
        if now is None or then is None or then == 0:
            return None
        return (now - then) / then * 100.0


FAPI_BASE = "https://fapi.binance.com/fapi/v1"


def fetch_open_interest(symbol: str) -> Optional[dict]:
    """Current open interest in contracts. Real exchange data, no API key."""
    try:
        r = requests.get(f"{FAPI_BASE}/openInterest",
                         params={"symbol": symbol_to_binance(symbol)}, timeout=FAPI_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return {"open_interest": float(data["openInterest"]), "time": int(data["time"])}
    except Exception as e:
        logger.error(f"Open interest fetch failed for {symbol}: {e}")
        return None


def fetch_liquidity_walls(symbol: str, reference_price: float,
                          within_pct: float = 2.0, limit: int = 500) -> Optional[dict]:
    """Largest resting bid/ask clusters near price, from the live order book.

    This is real posted liquidity — orders that actually exist — as opposed to
    the liquidation-cluster estimate below, which infers where stops *might* be
    from a volume profile. Walls are where price demonstrably has to absorb
    size, which is the more honest input to a discretionary decision.

    Live only: the order book has no history, so this informs a decision now
    and can never be backtested. It is reported as context, never as a gate.
    """
    if reference_price <= 0:
        return None
    try:
        r = requests.get(f"{FAPI_BASE}/depth",
                         params={"symbol": symbol_to_binance(symbol), "limit": limit},
                         timeout=FAPI_TIMEOUT)
        r.raise_for_status()
        book = r.json()
    except Exception as e:
        logger.error(f"Order book fetch failed for {symbol}: {e}")
        return None

    span = reference_price * within_pct / 100.0

    def biggest(levels, side):
        near = [(float(p), float(q)) for p, q in levels
                if abs(float(p) - reference_price) <= span]
        if not near:
            return None
        total = sum(q for _, q in near)
        price, qty = max(near, key=lambda x: x[1])
        return {
            "price": price,
            "qty": qty,
            "notional": price * qty,
            "share_of_side": qty / total if total else 0.0,
            "dist_pct": (price - reference_price) / reference_price * 100.0,
            "side": side,
        }

    bid_wall = biggest(book.get("bids", []), "bid")
    ask_wall = biggest(book.get("asks", []), "ask")
    bid_vol = sum(float(q) for p, q in book.get("bids", [])
                  if abs(float(p) - reference_price) <= span)
    ask_vol = sum(float(q) for p, q in book.get("asks", [])
                  if abs(float(p) - reference_price) <= span)
    total = bid_vol + ask_vol
    return {
        "bid_wall": bid_wall,
        "ask_wall": ask_wall,
        "bid_volume": bid_vol,
        "ask_volume": ask_vol,
        # >0.5 means more resting size below price than above.
        "bid_share": (bid_vol / total) if total else None,
        "within_pct": within_pct,
    }


def volume_context(df: pd.DataFrame, window: int = 24) -> Optional[dict]:
    """Latest candle volume against its recent average. Real OHLCV, no network."""
    if df is None or len(df) < window + 1:
        return None
    volumes = df["Volume"].astype(float)
    average = float(volumes.rolling(window).mean().iloc[-1])
    latest = float(volumes.iloc[-1])
    if not average or np.isnan(average):
        return None
    return {"latest": latest, "average": average, "ratio": latest / average}


def _round_relative(price: float, significant: int = 6) -> float:
    """Round to a fixed number of significant digits rather than decimals.

    Keeps the same relative precision whether the asset trades at $0.52 or
    $64,000, which a fixed decimal count cannot do.
    """
    if not price or not np.isfinite(price):
        return float(price)
    magnitude = int(np.floor(np.log10(abs(price))))
    return float(round(price, max(0, significant - 1 - magnitude)))


def _strength_label(density: float, density_max: float) -> str:
    if density_max <= 0:
        return "weak"
    if density >= density_max * 0.5:
        return "strong"
    if density >= density_max * 0.2:
        return "medium"
    return "weak"


def estimate_liquidation_clusters(df: pd.DataFrame, leverage: float = 10.0) -> Optional[dict]:
    """ESTIMATE liquidation clusters from a volume-at-price exposure profile.

    This is inferred, not observed. Binance does not serve market-wide
    liquidation history without an API key (/fapi/v1/forceOrders returns 401,
    /fapi/v1/allForceOrders is gone), so there is no real heatmap to read.

    The model assumes each candle's volume is positions entered across its price
    range, liquidated at entry/leverage for longs and entry*leverage for shorts,
    blended over 5x/10x/20x/50x. Every one of those assumptions is a guess: real
    traders do not enter uniformly across a candle, and their leverage is
    unknown. Treat the output as a hypothesis about where stops might sit.

    For actually-observed liquidity near price, use fetch_liquidity_walls(),
    which reads real resting orders from the book.
    """
    if df is None or len(df) < 60:
        return None
    closes = df["Close"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    highs = df["High"].to_numpy(float)
    volumes = df["Volume"].fillna(0.0).to_numpy(float)

    price_min, price_max = float(np.min(lows)), float(np.max(highs))
    if not (price_max > price_min):
        return None

    leverages = (5.0, 10.0, 20.0, 50.0)
    lo_frac = 1.0 / max(leverage, 2.0)
    grid_min = price_min * (1.0 - lo_frac)
    grid_max = price_max * (1.0 + lo_frac)

    n_bins = 60
    bins = np.linspace(grid_min, grid_max, n_bins + 1)
    mids = (bins[:-1] + bins[1:]) / 2.0
    density = np.zeros(n_bins)

    for i in range(len(df)):
        vol = volumes[i]
        if vol <= 0:
            continue
        lo, hi = float(lows[i]), float(highs[i])
        if not (hi > lo):
            continue
        b_lo = max(0, int(np.searchsorted(bins, lo, side="right") - 1))
        b_hi = min(n_bins - 1, int(np.searchsorted(bins, hi, side="right") - 1))
        if b_hi < b_lo:
            continue
        counts = np.zeros(n_bins)
        counts[b_lo:b_hi + 1] = 1.0
        counts *= vol / counts.sum()
        for b in range(b_lo, b_hi + 1):
            weight = counts[b]
            if weight <= 0:
                continue
            entry_price = float(mids[b])
            for lev in leverages:
                shift = 1.0 / lev
                for side_shift in (1.0 - shift, 1.0 + shift):
                    liq_price = entry_price * side_shift
                    if not (grid_min < liq_price < grid_max):
                        continue
                    liq_bin = int(np.searchsorted(bins, liq_price, side="right") - 1)
                    liq_bin = min(max(liq_bin, 0), n_bins - 1)
                    density[liq_bin] += weight * 0.5 / len(leverages)

    if not density.any():
        return None

    peaks = [
        i for i in range(1, n_bins - 1)
        if density[i] >= density[i - 1] and density[i] > density[i + 1]
    ]
    if not peaks:
        peaks = [int(np.argmax(density))]
    density_max = float(density.max())
    current = float(closes[-1])

    nearest_above = None
    nearest_below = None
    for idx in peaks:
        bin_low, bin_high = float(bins[idx]), float(bins[idx + 1])
        # Precision must scale with the price, not be fixed at two decimals.
        # At 2dp an XRP-priced asset moves in ~1% steps, and this price is
        # compared against a 3% proximity threshold — so a third of the gate
        # was rounding noise. Entry/SL/TP already snap to the exchange tick;
        # this closes the same hole on the one price that did not.
        peak_price = _round_relative((bin_low + bin_high) / 2)
        peak_density = float(density[idx])
        if bin_high > current and (nearest_above is None or peak_price < nearest_above["price"]):
            nearest_above = {
                "price": peak_price,
                "density": round(peak_density, 4),
                "strength": _strength_label(peak_density, density_max),
            }
        elif bin_low < current and (nearest_below is None or peak_price > nearest_below["price"]):
            nearest_below = {
                "price": peak_price,
                "density": round(peak_density, 4),
                "strength": _strength_label(peak_density, density_max),
            }

    return {"nearest_above": nearest_above, "nearest_below": nearest_below}