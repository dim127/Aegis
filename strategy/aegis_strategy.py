import json
from pathlib import Path

import ccxt
import pandas as pd

from indicators import (
    atr, detect_structure, fair_value_gaps, is_fvg_mitigated, latest_structure_event,
    is_breakout_candle, liquidity_inflection, order_block_for_event, detect_liquidity_sweep
)


class AegisSMCStrategy:

    DEFAULT_PAIRS = ["BTC", "ETH", "BNB", "SOL", "HYPE", "XRP", "LINK"]
    DEFAULT_RR_TARGET = 3.0
    DEFAULT_ATR_PROXIMITY = 2.0
    DEFAULT_MIN_CONFLUENCE = 3
    TIMEFRAME_DURATIONS = {"1m": pd.Timedelta(minutes=1), "15m": pd.Timedelta(minutes=15)}

    def __init__(self, exchange=None, config: dict | None = None):
        self.exchange = exchange or ccxt.hyperliquid({
            "enableRateLimit": True,
            "timeout": 20000,
        })
        config = config if config is not None else self._load_config()
        smc_config = config.get("smc", {})
        self.pairs = [self._normalize_pair(pair) for pair in config.get("smc_pairs", self.DEFAULT_PAIRS)]
        self.rr_target = float(smc_config.get("rr_target", self.DEFAULT_RR_TARGET))
        self.atr_proximity = float(smc_config.get("atr_proximity", self.DEFAULT_ATR_PROXIMITY))
        self.min_confluence = int(smc_config.get("min_confluence", self.DEFAULT_MIN_CONFLUENCE))

        if len(self.pairs) < 5:
            raise ValueError("smc_pairs must have at least 5 pairs")
        if self.rr_target < self.DEFAULT_RR_TARGET:
            raise ValueError("smc.rr_target cannot be below 3.0")
        if self.min_confluence < self.DEFAULT_MIN_CONFLUENCE or self.min_confluence > 5:
            raise ValueError("smc.min_confluence must be between 3 and 5")

    @staticmethod
    def _load_config() -> dict:
        config_path = Path(__file__).resolve().parents[1] / "aegis_config.json"
        if not config_path.exists():
            return {}
        with config_path.open() as config_file:
            return json.load(config_file)

    @staticmethod
    def _normalize_pair(pair: str) -> str:
        return pair if "/" in pair else f"{pair}/USDC:USDC"

    def _ohlcv_to_df(self, raw: list, timeframe: str, now=None) -> pd.DataFrame | None:
        if not raw or len(raw) < 50:
            return None
        df = pd.DataFrame(raw, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        duration = self.TIMEFRAME_DURATIONS[timeframe]
        now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        df = df.loc[df.index + duration <= now]
        return df if len(df) >= 50 else None

    def _check_direction(self, df_15m: pd.DataFrame, df_1m: pd.DataFrame, direction: str) -> dict:
        bull_dir = direction == "long"

        structure_15m = latest_structure_event(df_15m, direction, window=15)
        atr_15m_val = atr(df_15m, period=14).iloc[-1] if len(df_15m) > 14 else 0

        structure_1m = detect_structure(df_1m, window=15)
        atr_1m_val = atr(df_1m, period=14).iloc[-1] if len(df_1m) > 14 else 0
        fvg_1m_info = fair_value_gaps(df_1m, lookback=60)

        if bull_dir:
            struct_15m = structure_15m["bullish_choch"] or structure_15m["bullish_bos"]
            confirm_1m = structure_1m["bullish_choch"]
            fvg_below = fvg_1m_info["bullish_fvgs"]
        else:
            struct_15m = structure_15m["bearish_choch"] or structure_15m["bearish_bos"]
            confirm_1m = structure_1m["bearish_choch"]
            fvg_below = fvg_1m_info["bearish_fvgs"]

        # 1. 15m structure shift
        reason_15m = None
        if structure_15m["bullish_choch"] if bull_dir else structure_15m["bearish_choch"]:
            reason_15m = f"15M CHOCH {'Bullish' if bull_dir else 'Bearish'}"
        elif structure_15m["bullish_bos"] if bull_dir else structure_15m["bearish_bos"]:
            reason_15m = f"15M BOS {'Bullish' if bull_dir else 'Bearish'}"

        # 2. 1m CHOCH alignment
        reason_1m = None
        if confirm_1m:
            reason_1m = f"1M CHOCH {'Bullish' if bull_dir else 'Bearish'} aligned"

        # 3. FVG on 1m
        best_fvg = None
        reason_fvg = None
        structure_events = [
            event for event in [structure_15m["event"], structure_1m["event"]]
            if event is not None and event["direction"] == direction
        ]
        structure_time = max((event["index"] for event in structure_events), default=None)
        if bull_dir:
            sorted_fvgs = sorted(fvg_below, key=lambda x: x["gap_high"], reverse=True)
            if sorted_fvgs:
                for fvg in sorted_fvgs:
                    if structure_time is not None and fvg["index"] < structure_time:
                        continue
                    if not is_fvg_mitigated(df_1m, fvg["gap_low"], fvg["gap_high"], fvg["index"]):
                        best_fvg = fvg
                        break
            if best_fvg:
                reason_fvg = f"1M Bullish FVG ${best_fvg['gap_low']:.2f}-${best_fvg['gap_high']:.2f} (fresh)"
        else:
            sorted_fvgs = sorted(fvg_below, key=lambda x: x["gap_low"])
            if sorted_fvgs:
                for fvg in sorted_fvgs:
                    if structure_time is not None and fvg["index"] < structure_time:
                        continue
                    if not is_fvg_mitigated(df_1m, fvg["gap_low"], fvg["gap_high"], fvg["index"]):
                        best_fvg = fvg
                        break
            if best_fvg:
                reason_fvg = f"1M Bearish FVG ${best_fvg['gap_low']:.2f}-${best_fvg['gap_high']:.2f} (fresh)"

        entry = best_fvg["gap_mid"] if best_fvg else None

        # 4. OB from the 15m structure displacement, measured against the limit entry.
        reason_ob = None
        structure_event_15m = structure_15m["event"] if struct_15m else None
        associated_ob = None
        if entry is not None and structure_event_15m is not None:
            associated_ob = order_block_for_event(df_15m, structure_event_15m["index"], direction)
            if associated_ob is not None and not associated_ob["fully_mitigated"] and associated_ob["mitigation_ratio"] < 0.5 and atr_15m_val > 0:
                ob_price = associated_ob["high"] if bull_dir else associated_ob["low"]
                dist = abs(entry - ob_price)
                if dist < atr_15m_val * self.atr_proximity:
                    reason_ob = f"{'Bullish' if bull_dir else 'Bearish'} OB ${ob_price:.2f} ({dist/atr_15m_val:.1f} ATR)"

        # 5. Breakout candle impulse
        reason_breakout = None
        if is_breakout_candle(df_1m, direction, lookback=5, vol_multiplier=1.15):
            reason_breakout = "1M impulsive + volume spike"
            
        # 6. Liquidity Sweep before CHOCH
        reason_sweep = None
        if structure_time is not None and detect_liquidity_sweep(df_1m, direction, before=structure_time, window=30):
            reason_sweep = f"1M Liquidity Sweep before CHOCH"

        # Mandatory: structure shift (15m CHOCH/BOS OR 1m CHOCH).
        has_structure = struct_15m or confirm_1m
        if not has_structure:
            return {"valid": False, "reason": "No structure shift (15m/1m CHOCH/BOS)",
                    "reasons": [], "confluence": 0}

        # Mandatory: fresh FVG
        if best_fvg is None:
            return {"valid": False, "reason": "No valid FVG for entry",
                    "reasons": [r for r in [reason_15m, reason_1m] if r], "confluence": 0}

        # Mandatory: liquidity sweep (break + reversal confirmation)
        if reason_sweep is None:
            return {"valid": False, "reason": "No liquidity sweep before structure shift",
                    "reasons": [r for r in [reason_15m, reason_1m, reason_fvg] if r], "confluence": 0}

        reasons = [r for r in [reason_15m, reason_1m, reason_fvg, reason_ob, reason_breakout, reason_sweep] if r]
        confluence = len(reasons)

        if confluence < self.min_confluence:
            return {"valid": False, "reason": f"Confluence too low: {confluence}/5",
                    "reasons": reasons, "confluence": confluence}

        sl = liquidity_inflection(df_1m, direction, before=best_fvg["index"])
        if sl is None:
            return {"valid": False, "reason": "No confirmed swing before FVG for Stop Loss"}
            
        sl_buffer = atr_1m_val * 1.5
        if bull_dir:
            sl -= sl_buffer
        else:
            sl += sl_buffer

        if bull_dir:
            risk = entry - sl
            if risk <= 0:
                return {"valid": False, "reason": f"Invalid SL: entry ${entry:.2f} <= SL ${sl:.2f}"}
            tp = entry + (risk * self.rr_target)
        else:
            risk = sl - entry
            if risk <= 0:
                return {"valid": False, "reason": f"Invalid SL: entry ${entry:.2f} >= SL ${sl:.2f}"}
            tp = entry - (risk * self.rr_target)

        rr = (tp - entry) / risk if bull_dir else (entry - tp) / risk

        action = "BUY LIMIT" if bull_dir else "SELL LIMIT"

        if reason_15m:
            htf_bias_text = f"{'Bullish' if bull_dir else 'Bearish'} - {reason_15m}"
        else:
            htf_bias_text = f"{'Bullish' if bull_dir else 'Bearish'} - {reason_1m or 'BOS'}"

        if confirm_1m and reason_fvg:
            ltf_conf_text = "Valid CHOCH + FVG"
        elif reason_fvg:
            ltf_conf_text = "Valid FVG (no 1M CHOCH)"
        else:
            ltf_conf_text = "Invalid"

        return {
            "valid": True,
            "direction": direction,
            "action": action,
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "rr": round(rr, 2),
            "risk": round(risk, 2),
            "confluence": confluence,
            "reasons": reasons,
            "timestamp": df_1m.index[-1],
            "structure_15m": structure_15m["event"],
            "structure_1m": structure_1m["event"],
            "fvg_timestamp": best_fvg["index"],
            "ob_timestamp": associated_ob["index"] if associated_ob else None,
            "htf_bias_text": htf_bias_text,
            "ltf_conf_text": ltf_conf_text,
            "management_rules": "Hold until Stop Loss or Take Profit.",
        }

    def analyze_pair(self, sym: str) -> dict | None:
        base = sym.split("/")[0]
        raw_15m = self.exchange.fetch_ohlcv(sym, "15m", limit=100)
        raw_1m = self.exchange.fetch_ohlcv(sym, "1m", limit=120)
        df_15m = self._ohlcv_to_df(raw_15m, "15m")
        df_1m = self._ohlcv_to_df(raw_1m, "1m")
        if df_15m is None or df_1m is None:
            return None

        best = None
        for direction in ["long", "short"]:
            result = self._check_direction(df_15m, df_1m, direction)
            if result["valid"]:
                result["pair"] = sym
                result["base"] = base
                if best is None or result["rr"] > best["rr"]:
                    best = result
        return best

    def analyze(self) -> list[dict]:
        results = []
        for sym in self.pairs:
            try:
                setup = self.analyze_pair(sym)
                if setup:
                    results.append(setup)
            except Exception as e:
                print(f"  ERROR {sym}: {e}")
        return results
