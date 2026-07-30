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
    TIMEFRAME_DURATIONS = {"1m": pd.Timedelta(minutes=1), "5m": pd.Timedelta(minutes=5), "15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4)}

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

    def _check_direction(self, df_htf: pd.DataFrame, df_ltf: pd.DataFrame, direction: str, tf_htf: str, tf_ltf: str) -> dict:
        bull_dir = direction == "long"

        structure_htf = latest_structure_event(df_htf, direction, window=15)
        atr_htf_val = atr(df_htf, period=14).iloc[-1] if len(df_htf) > 14 else 0

        structure_ltf = detect_structure(df_ltf, window=15)
        atr_ltf_val = atr(df_ltf, period=14).iloc[-1] if len(df_ltf) > 14 else 0
        fvg_ltf_info = fair_value_gaps(df_ltf, lookback=60)

        if bull_dir:
            struct_htf = structure_htf["bullish_choch"] or structure_htf["bullish_bos"]
            confirm_ltf = structure_ltf["bullish_choch"]
            fvg_below = fvg_ltf_info["bullish_fvgs"]
        else:
            struct_htf = structure_htf["bearish_choch"] or structure_htf["bearish_bos"]
            confirm_ltf = structure_ltf["bearish_choch"]
            fvg_below = fvg_ltf_info["bearish_fvgs"]

        # 1. 15m structure shift
        reason_htf = None
        if structure_htf["bullish_choch"] if bull_dir else structure_htf["bearish_choch"]:
            reason_htf = f"{tf_htf.upper()} CHOCH {'Bullish' if bull_dir else 'Bearish'}"
        elif structure_htf["bullish_bos"] if bull_dir else structure_htf["bearish_bos"]:
            reason_htf = f"{tf_htf.upper()} BOS {'Bullish' if bull_dir else 'Bearish'}"

        # 2. 1m CHOCH alignment
        reason_ltf = None
        if confirm_ltf:
            reason_ltf = f"{tf_ltf.upper()} CHOCH {'Bullish' if bull_dir else 'Bearish'} aligned"

        # 3. FVG on 1m
        best_fvg = None
        reason_fvg = None
        structure_events = [
            event for event in [structure_htf["event"], structure_ltf["event"]]
            if event is not None and event["direction"] == direction
        ]
        structure_time = max((event["index"] for event in structure_events), default=None)
        if bull_dir:
            sorted_fvgs = sorted(fvg_below, key=lambda x: x["gap_high"], reverse=True)
            if sorted_fvgs:
                for fvg in sorted_fvgs:
                    if structure_time is not None and fvg["index"] < structure_time:
                        continue
                    if not is_fvg_mitigated(df_ltf, fvg["gap_low"], fvg["gap_high"], fvg["index"]):
                        best_fvg = fvg
                        break
            if best_fvg:
                reason_fvg = f"{tf_ltf.upper()} Bullish FVG ${best_fvg['gap_low']:.2f}-${best_fvg['gap_high']:.2f} (fresh)"
        else:
            sorted_fvgs = sorted(fvg_below, key=lambda x: x["gap_low"])
            if sorted_fvgs:
                for fvg in sorted_fvgs:
                    if structure_time is not None and fvg["index"] < structure_time:
                        continue
                    if not is_fvg_mitigated(df_ltf, fvg["gap_low"], fvg["gap_high"], fvg["index"]):
                        best_fvg = fvg
                        break
            if best_fvg:
                reason_fvg = f"{tf_ltf.upper()} Bearish FVG ${best_fvg['gap_low']:.2f}-${best_fvg['gap_high']:.2f} (fresh)"

        entry = best_fvg["gap_mid"] if best_fvg else None

        # 4. OB from the 15m structure displacement, measured against the limit entry.
        reason_ob = None
        structure_event_htf = structure_htf["event"] if struct_htf else None
        associated_ob = None
        if entry is not None and structure_event_htf is not None:
            associated_ob = order_block_for_event(df_htf, structure_event_htf["index"], direction)
            if associated_ob is not None and not associated_ob["fully_mitigated"] and associated_ob["mitigation_ratio"] < 0.5 and atr_htf_val > 0:
                ob_price = associated_ob["high"] if bull_dir else associated_ob["low"]
                dist = abs(entry - ob_price)
                if dist < atr_htf_val * self.atr_proximity:
                    reason_ob = f"{'Bullish' if bull_dir else 'Bearish'} OB ${ob_price:.2f} ({dist/atr_htf_val:.1f} ATR)"

        # 5. Breakout candle impulse
        reason_breakout = None
        if is_breakout_candle(df_ltf, direction, lookback=5, vol_multiplier=1.15):
            reason_breakout = f"{tf_ltf.upper()} impulsive + volume spike"
            
        # 6. Liquidity Sweep before CHOCH
        reason_sweep = None
        if structure_time is not None and detect_liquidity_sweep(df_ltf, direction, before=structure_time, window=30):
            reason_sweep = f"{tf_ltf.upper()} Liquidity Sweep before CHOCH"

        # Mandatory: structure shift (15m CHOCH/BOS OR 1m CHOCH).
        has_structure = struct_htf or confirm_ltf
        if not has_structure:
            return {"valid": False, "reason": f"No structure shift ({tf_htf}/{tf_ltf} CHOCH/BOS)",
                    "reasons": [], "confluence": 0}

        # Mandatory: fresh FVG
        if best_fvg is None:
            return {"valid": False, "reason": "No valid FVG for entry",
                    "reasons": [r for r in [reason_htf, reason_ltf] if r], "confluence": 0}

        # Mandatory: liquidity sweep (break + reversal confirmation)
        if reason_sweep is None:
            return {"valid": False, "reason": "No liquidity sweep before structure shift",
                    "reasons": [r for r in [reason_htf, reason_ltf, reason_fvg] if r], "confluence": 0}

        reasons = [r for r in [reason_htf, reason_ltf, reason_fvg, reason_ob, reason_breakout, reason_sweep] if r]
        confluence = len(reasons)

        if confluence < self.min_confluence:
            return {"valid": False, "reason": f"Confluence too low: {confluence}/5",
                    "reasons": reasons, "confluence": confluence}

        sl = liquidity_inflection(df_ltf, direction, before=best_fvg["index"])
        if sl is None:
            return {"valid": False, "reason": "No confirmed swing before FVG for Stop Loss"}
            
        sl_buffer = atr_ltf_val * 1.5
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

        if reason_htf:
            htf_bias_text = f"{'Bullish' if bull_dir else 'Bearish'} - {reason_htf}"
        else:
            htf_bias_text = f"{'Bullish' if bull_dir else 'Bearish'} - {reason_ltf or 'BOS'}"

        if confirm_ltf and reason_fvg:
            ltf_conf_text = f"Valid {tf_ltf.upper()} CHOCH + FVG"
        elif reason_fvg:
            ltf_conf_text = f"Valid FVG (no {tf_ltf.upper()} CHOCH)"
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
            "timestamp": df_ltf.index[-1],
            "structure_htf": structure_htf["event"],
            "structure_ltf": structure_ltf["event"],
            "fvg_timestamp": best_fvg["index"],
            "ob_timestamp": associated_ob["index"] if associated_ob else None,
            "htf_bias_text": htf_bias_text,
            "ltf_conf_text": ltf_conf_text,
            "management_rules": "Hold until Stop Loss or Take Profit.",
        }

    def analyze_pair(self, sym: str, tf_htf: str, tf_ltf: str) -> dict | None:
        base = sym.split("/")[0]
        raw_htf = self.exchange.fetch_ohlcv(sym, tf_htf, limit=100)
        raw_ltf = self.exchange.fetch_ohlcv(sym, tf_ltf, limit=120)
        df_htf = self._ohlcv_to_df(raw_htf, tf_htf)
        df_ltf = self._ohlcv_to_df(raw_ltf, tf_ltf)
        if df_htf is None or df_ltf is None:
            return None

        best = None
        for direction in ["long", "short"]:
            result = self._check_direction(df_htf, df_ltf, direction, tf_htf, tf_ltf)
            if result["valid"]:
                result["pair"] = sym
                result["base"] = base
                result["tf_combo"] = f"{tf_htf}/{tf_ltf}"
                if best is None or result["rr"] > best["rr"]:
                    best = result
        return best

    def analyze(self) -> list[dict]:
        results = []
        combinations = [("15m", "1m"), ("1h", "5m"), ("4h", "15m")]
        for sym in self.pairs:
            for tf_htf, tf_ltf in combinations:
                try:
                    setup = self.analyze_pair(sym, tf_htf, tf_ltf)
                    if setup:
                        results.append(setup)
                except Exception as e:
                    print(f"  ERROR {sym} ({tf_htf}/{tf_ltf}): {e}")
        return results
