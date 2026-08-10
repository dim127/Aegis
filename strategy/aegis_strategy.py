"""Aegis — ICT reversal detection on Hyperliquid perpetuals.

The two timeframes have different jobs. The HTF supplies the *zone*; the LTF
supplies the *confirmation*. Demanding a structure shift on both was the earlier
mistake — it asked the higher timeframe to do the lower one's work, and rejected
every candidate.

Sequence, in order, all required:

    1. POI          an unmitigated FVG on the HTF — the zone price must reach
    2. Retracement  price actually trades back into that zone
    3. Sweep        liquidity taken *inside* the POI, then reclaimed
    4. MSS          a structure shift on the LTF, breaking the sweep — the
                    confirmation that the reversal is underway
    5. Entry        a fresh LTF FVG sitting in the OTE band (61.8-78.6%) of the
                    leg that produced the MSS

Nothing is scored, counted or weighted. There is no 3/8 to reach and no minimum
tally — a score can sit at 4/8 and mean nothing in particular, which is the
ambiguity that made setups equivocal. Each condition is binary, checked in
order, and a rejection always names the step that failed.

Levels come from the structure that produced the setup:

    entry   the OTE-zone FVG midpoint
    stop    behind the sweep itself — the level whose violation disproves the
            reversal thesis
    target  the nearest opposing swing, where the liquidity actually sits

So R is an *output*, not an input: whatever the distance between those levels
makes it, rather than a number chosen in advance and imposed on the chart.
"""
import json
from pathlib import Path

import ccxt
import pandas as pd

from indicators import (
    atr, detect_structure, fair_value_gaps, is_fvg_mitigated, latest_structure_event,
    liquidity_inflection, liquidity_target, find_liquidity_sweep, ote_zone,
)


class AegisSMCStrategy:

    DEFAULT_PAIRS = ["BTC", "ETH", "BNB", "SOL", "HYPE", "XRP", "LINK"]
    DEFAULT_RR_TARGET = 3.0
    QUOTE = "USDC"
    TIMEFRAME_DURATIONS = {
        "1m": pd.Timedelta(minutes=1), "5m": pd.Timedelta(minutes=5),
        "15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1),
        "4h": pd.Timedelta(hours=4),
    }
    COMBINATIONS = [("15m", "1m"), ("1h", "5m"), ("4h", "15m")]

    def __init__(self, exchange=None, config: dict | None = None):
        if exchange is None:
            exchange = ccxt.hyperliquid({"enableRateLimit": True, "timeout": 20000})
        self.exchange = exchange
        config = config if config is not None else self._load_config()
        smc_config = config.get("smc", {})
        self.pairs = [self._normalize_pair(p) for p in config.get("smc_pairs", self.DEFAULT_PAIRS)]
        self.rr_target = float(smc_config.get("rr_target", self.DEFAULT_RR_TARGET))
        self.sl_atr_buffer = float(smc_config.get("sl_atr_buffer", 1.5))

        if len(self.pairs) < 1:
            raise ValueError("smc_pairs must not be empty")
        if self.rr_target <= 0:
            raise ValueError("smc.rr_target must be positive")

    @staticmethod
    def _load_config() -> dict:
        config_path = Path(__file__).resolve().parents[1] / "aegis_config.json"
        if not config_path.exists():
            return {}
        with config_path.open() as config_file:
            return json.load(config_file)

    @classmethod
    def _normalize_pair(cls, pair: str) -> str:
        return pair if "/" in pair else f"{pair}/{cls.QUOTE}:{cls.QUOTE}"

    @staticmethod
    def _fmt(price: float) -> str:
        """Decimals scaled to magnitude, so sub-dollar pairs stay readable."""
        magnitude = abs(price)
        if magnitude >= 1000:
            decimals = 2
        elif magnitude >= 10:
            decimals = 3
        elif magnitude >= 1:
            decimals = 4
        else:
            decimals = 6
        return f"{price:.{decimals}f}"

    def _quantizer(self, symbol: str):
        """Snap prices to the exchange tick, so a quoted level can actually exist."""
        exchange = self.exchange
        if not hasattr(exchange, "price_to_precision"):
            return None
        try:
            if not getattr(exchange, "markets", None):
                exchange.load_markets()
        except Exception as e:
            print(f"  market load failed for {symbol}: {e}")
            return None

        def quantize(price: float) -> float:
            try:
                return float(exchange.price_to_precision(symbol, price))
            except Exception:
                return price

        return quantize

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
        # Drop the still-forming candle. Structure read from a bar that can
        # still change is structure that can un-happen.
        df = df.loc[df.index + duration <= now]
        return df if len(df) >= 50 else None

    @staticmethod
    def _htf_context(df_htf: pd.DataFrame, direction: str) -> tuple:
        """Heavy HTF analysis, reused across identical slices during a replay."""
        structure_htf = latest_structure_event(df_htf, direction, window=15)
        atr_htf_val = atr(df_htf, period=14).iloc[-1] if len(df_htf) > 14 else 0
        return structure_htf, atr_htf_val

    def _check_direction(self, df_htf: pd.DataFrame, df_ltf: pd.DataFrame, direction: str,
                         tf_htf: str = "15m", tf_ltf: str = "1m",
                         htf_context: tuple | None = None, quantize=None) -> dict:
        bull_dir = direction == "long"
        quantize = quantize or (lambda price: price)

        if htf_context is not None:
            structure_htf, _ = htf_context
        else:
            structure_htf, _ = self._htf_context(df_htf, direction)

        structure_ltf = detect_structure(df_ltf, window=15)
        atr_ltf_val = atr(df_ltf, period=14).iloc[-1] if len(df_ltf) > 14 else 0
        fvg_info = fair_value_gaps(df_ltf, lookback=60)
        fvg_htf = fair_value_gaps(df_htf, lookback=60)

        # ---- 1. HTF point of interest: an unmitigated FVG -------------------
        # The higher timeframe supplies the zone, not a confirmation. Requiring
        # an MSS here asks it to do the lower timeframe's job.
        htf_fvgs = (fvg_htf["bullish_fvgs"] if bull_dir else fvg_htf["bearish_fvgs"])
        poi = None
        for fvg in sorted(htf_fvgs, key=lambda f: f["index"], reverse=True):
            if not is_fvg_mitigated(df_htf, fvg["gap_low"], fvg["gap_high"], fvg["index"]):
                poi = fvg
                break
        if poi is None:
            return {"valid": False, "reason": f"No unmitigated {tf_htf} FVG (POI)"}

        # ---- 2. Price retraced into the POI --------------------------------
        low_now = float(df_ltf["Low"].iloc[-1])
        high_now = float(df_ltf["High"].iloc[-1])
        touched = (df_ltf["Low"].tail(60) <= poi["gap_high"]).any() and \
                  (df_ltf["High"].tail(60) >= poi["gap_low"]).any()
        if not touched:
            return {"valid": False, "reason": f"Price has not retraced into the {tf_htf} FVG"}

        # ---- 3. Liquidity sweep inside the POI ------------------------------
        sweep = find_liquidity_sweep(df_ltf, direction, window=30)
        if sweep is None:
            return {"valid": False, "reason": "No liquidity sweep"}
        if not (poi["gap_low"] <= sweep["price"] <= poi["gap_high"]):
            return {"valid": False,
                    "reason": f"Sweep at {self._fmt(sweep['price'])} sits outside the {tf_htf} FVG"}

        # ---- 4. MSS on the LTF, breaking the sweep --------------------------
        # The confirmation, and it must come after the sweep it confirms.
        if bull_dir:
            ltf_shift = structure_ltf["bullish_choch"] or structure_ltf["bullish_bos"]
        else:
            ltf_shift = structure_ltf["bearish_choch"] or structure_ltf["bearish_bos"]
        if not ltf_shift:
            return {"valid": False, "reason": f"No MSS on {tf_ltf} after the sweep"}

        mss_event = structure_ltf["event"]
        if mss_event is None or mss_event["direction"] != direction:
            return {"valid": False, "reason": f"No {tf_ltf} MSS in this direction"}
        structure_time = mss_event["index"]
        event_kind = mss_event["kind"]
        if structure_time <= sweep["index"]:
            return {"valid": False, "reason": "MSS did not follow the sweep"}

        # The MSS must break a swing belonging to the leg the sweep produced,
        # not merely happen afterwards. Without this, a break of some unrelated
        # older swing counts as confirmation of a reversal it says nothing
        # about — the sweep and the shift would only share a direction and an
        # ordering, which is coincidence rather than structure.
        broken = mss_event.get("broken_swing_index")
        if broken is None or broken < sweep["index"]:
            return {"valid": False,
                    "reason": "MSS broke a swing older than the sweep"}

        # ---- 5. Entry: LTF FVG inside the OTE of the MSS leg ----------------
        leg = df_ltf.loc[sweep["index"]:structure_time]
        leg_low, leg_high = float(leg["Low"].min()), float(leg["High"].max())
        ote_low, ote_high = ote_zone(leg_low, leg_high, direction)

        candidate_fvgs = (fvg_info["bullish_fvgs"] if bull_dir else fvg_info["bearish_fvgs"])
        best_fvg = None
        for fvg in sorted(candidate_fvgs, key=lambda f: f["index"], reverse=True):
            if fvg["index"] < sweep["index"]:
                continue
            if is_fvg_mitigated(df_ltf, fvg["gap_low"], fvg["gap_high"], fvg["index"]):
                continue
            if ote_low <= fvg["gap_mid"] <= ote_high:
                best_fvg = fvg
                break
        if best_fvg is None:
            return {"valid": False,
                    "reason": (f"No fresh {tf_ltf} FVG inside OTE "
                               f"{self._fmt(ote_low)}-{self._fmt(ote_high)}")}

        # ---- 6. Levels -------------------------------------------------------
        entry = quantize(best_fvg["gap_mid"])
        # Stop goes behind the sweep itself — the level whose violation would
        # mean the reversal thesis was wrong.
        buffer = atr_ltf_val * self.sl_atr_buffer
        swing = sweep["price"]
        sl = quantize(swing - buffer if bull_dir else swing + buffer)

        risk = (entry - sl) if bull_dir else (sl - entry)
        if risk <= 0:
            return {"valid": False,
                    "reason": f"Invalid stop: entry {self._fmt(entry)} vs SL {self._fmt(sl)}"}

        # Target the liquidity, then let R fall out of it. A swing is where
        # resting orders actually sit, so it is a reason for price to travel;
        # a fixed multiple is only a number someone picked. Falls back to the
        # multiple when no opposing swing is in range.
        target = liquidity_target(df_ltf, direction, entry, window=60)
        if target is not None:
            tp = quantize(target)
            reward = (tp - entry) if bull_dir else (entry - tp)
            tp_source = "swing"
        else:
            tp = quantize(entry + risk * self.rr_target if bull_dir
                          else entry - risk * self.rr_target)
            reward = risk * self.rr_target
            tp_source = "multiple"

        if reward <= 0:
            return {"valid": False, "reason": "Target sits on the wrong side of entry"}
        rr = reward / risk

        ltf_kind = structure_ltf["event"]["kind"] if structure_ltf["event"] else "MSS"
        side = "Bullish" if bull_dir else "Bearish"
        return {
            "valid": True,
            "direction": direction,
            "action": "BUY LIMIT" if bull_dir else "SELL LIMIT",
            "poi_label": (f"{tf_htf.upper()} FVG {self._fmt(poi['gap_low'])}"
                          f"-{self._fmt(poi['gap_high'])} (POI)"),
            "sweep_label": (f"sweep {self._fmt(sweep['price'])} di dalam POI "
                            f"(ambil {self._fmt(sweep['swept_level'])})"),
            "mss_label": f"{tf_ltf.upper()} MSS {ltf_kind} {side}",
            "ote_label": f"OTE {self._fmt(ote_low)}-{self._fmt(ote_high)}",
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "risk": risk,
            "risk_pct": round(risk / entry * 100.0, 3),
            "rr": round(rr, 2),
            "tp_source": tp_source,
            "tp_label": (f"swing {'high' if bull_dir else 'low'} {self._fmt(tp)}"
                         if tp_source == "swing" else f"{self.rr_target:.0f}R multiple"),
            "event_kind": event_kind,
            "sweep_price": sweep["price"],
            "ote_low": ote_low,
            "ote_high": ote_high,
            "fvg_label": (f"{tf_ltf.upper()} FVG {self._fmt(best_fvg['gap_low'])}"
                          f"-{self._fmt(best_fvg['gap_high'])} (entry, dalam OTE)"),
            "timestamp": df_ltf.index[-1],
            "structure_htf": structure_htf["event"],
            "structure_ltf": structure_ltf["event"],
            "fvg_timestamp": best_fvg["index"],
            "structure_time": structure_time,
            "management_rules": "Hold until Stop Loss or Take Profit.",
        }

    def analyze_pair(self, sym: str, tf_htf: str, tf_ltf: str) -> dict | None:
        raw_htf = self.exchange.fetch_ohlcv(sym, tf_htf, limit=200)
        raw_ltf = self.exchange.fetch_ohlcv(sym, tf_ltf, limit=200)
        df_htf = self._ohlcv_to_df(raw_htf, tf_htf)
        df_ltf = self._ohlcv_to_df(raw_ltf, tf_ltf)
        if df_htf is None or df_ltf is None:
            return None

        quantize = self._quantizer(sym)
        best = None
        for direction in ("long", "short"):
            result = self._check_direction(df_htf, df_ltf, direction, tf_htf, tf_ltf,
                                           quantize=quantize)
            if not result["valid"]:
                continue
            result["pair"] = sym
            result["base"] = sym.split("/")[0]
            result["tf_combo"] = f"{tf_htf}/{tf_ltf}"
            result["tf_htf"] = tf_htf
            result["tf_ltf"] = tf_ltf
            # Both directions qualifying is rare and means structure is
            # contested; take the fresher gap rather than scoring them.
            if best is None or result["fvg_timestamp"] > best["fvg_timestamp"]:
                best = result
        return best

    def _journal_signal(self, setup: dict) -> None:
        try:
            import db
            entry = dict(setup)
            entry["signal_time"] = setup["timestamp"].isoformat()
            if db.save_signal(entry):
                print(f"  journal: {setup['pair']} {setup['direction']} "
                      f"entry {self._fmt(setup['entry'])} @ {entry['signal_time']}")
            db.log_signal(setup)
        except Exception as e:
            print(f"  journal error: {e}")

    def analyze(self) -> list[dict]:
        results = []
        for sym in self.pairs:
            for tf_htf, tf_ltf in self.COMBINATIONS:
                try:
                    setup = self.analyze_pair(sym, tf_htf, tf_ltf)
                    if setup:
                        results.append(setup)
                        self._journal_signal(setup)
                except Exception as e:
                    print(f"  ERROR {sym} ({tf_htf}/{tf_ltf}): {e}")
        return results
