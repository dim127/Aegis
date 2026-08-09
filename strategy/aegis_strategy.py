import json
from pathlib import Path

import ccxt
import pandas as pd

from indicators import (
    atr, detect_structure, fair_value_gaps, is_fvg_mitigated, latest_structure_event,
    is_breakout_candle, liquidity_inflection, order_block_for_event, detect_liquidity_sweep
)
from market_metrics import (
    PositioningSeries, estimate_liquidation_clusters, fetch_liquidity_walls,
    fetch_open_interest, long_short_24h, volume_context,
)


class AegisSMCStrategy:

    DEFAULT_PAIRS = ["BTC", "ETH", "BNB", "SOL", "HYPE", "XRP", "LINK"]
    DEFAULT_RR_TARGET = 3.0
    DEFAULT_ATR_PROXIMITY = 2.0
    DEFAULT_MIN_CONFLUENCE = 3
    # Structure, FVG and sweep are mandatory, and each contributes exactly one
    # reason — so total confluence is >= 3 before any threshold is consulted,
    # which is why min_confluence could never reject anything. Only the soft
    # factors carry information a threshold can act on.
    HARD_FACTORS = ("structure", "fvg", "sweep")
    SOFT_FACTORS = ("ob", "breakout", "long_short", "cluster")
    DEFAULT_COSTS = {
        "maker_fee_pct": 0.02,
        "taker_fee_pct": 0.04,
        "slippage_pct": 0.02,
        "min_cost_multiple": 8.0,
    }
    TIMEFRAME_DURATIONS = {"1m": pd.Timedelta(minutes=1), "5m": pd.Timedelta(minutes=5), "15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4)}

    def __init__(self, exchange=None, config: dict | None = None):
        if exchange is None:
            exchange = ccxt.binanceusdm({
                "enableRateLimit": True,
                "timeout": 20000,
                "options": {"defaultType": "future"},
            })
        self.exchange = exchange
        config = config if config is not None else self._load_config()
        smc_config = config.get("smc", {})
        self.pairs = [self._normalize_pair(pair) for pair in config.get("smc_pairs", self.DEFAULT_PAIRS)]
        self.rr_target = float(smc_config.get("rr_target", self.DEFAULT_RR_TARGET))
        self.atr_proximity = float(smc_config.get("atr_proximity", self.DEFAULT_ATR_PROXIMITY))
        self.min_confluence = int(smc_config.get("min_confluence", self.DEFAULT_MIN_CONFLUENCE))
        # Defaults to 0: confluence scored p=1.000 against outcomes over 79
        # trades, so a tighter gate would cut signal volume with no evidence of
        # better quality. Making the knob work is correctness; turning it up
        # without data would be guessing.
        self.min_soft_confluence = int(smc_config.get("min_soft_confluence", 0))

        market_cfg = smc_config.get("market", {})
        self.long_short_enabled = bool(market_cfg.get("long_short_enabled", True))
        self.liquidation_enabled = bool(market_cfg.get("liquidation_enabled", True))
        self.liquidation_leverage = float(market_cfg.get("liquidation_leverage", 10.0))
        self.cluster_proximity_pct = float(market_cfg.get("cluster_proximity_pct", 3.0))
        self.market_cache_minutes = int(market_cfg.get("cache_minutes", 60))
        self.long_short_source = market_cfg.get("long_short_source", "top_position")

        # Round-trip cost: maker on the limit entry, taker on the STOP_MARKET /
        # TAKE_PROFIT_MARKET exit, plus expected slippage on the market exit.
        costs = {**self.DEFAULT_COSTS, **config.get("risk", {}).get("costs", {})}
        self.round_trip_cost_pct = (
            float(costs["maker_fee_pct"])
            + float(costs["taker_fee_pct"])
            + float(costs["slippage_pct"])
        )
        self.min_cost_multiple = float(costs["min_cost_multiple"])
        self.min_stop_pct = self.round_trip_cost_pct * self.min_cost_multiple

        if len(self.pairs) < 5:
            raise ValueError("smc_pairs must have at least 5 pairs")
        if self.rr_target < self.DEFAULT_RR_TARGET:
            raise ValueError("smc.rr_target cannot be below 3.0")
        if self.min_confluence < self.DEFAULT_MIN_CONFLUENCE or self.min_confluence > 8:
            raise ValueError("smc.min_confluence must be between 3 and 8")

    @staticmethod
    def _load_config() -> dict:
        config_path = Path(__file__).resolve().parents[1] / "aegis_config.json"
        if not config_path.exists():
            return {}
        with config_path.open() as config_file:
            return json.load(config_file)

    @staticmethod
    def _normalize_pair(pair: str) -> str:
        return pair if "/" in pair else f"{pair}/USDT:USDT"

    @classmethod
    def _count_soft(cls, factor_names) -> int:
        """How many optional factors fired, ignoring the mandatory three."""
        return sum(1 for name in factor_names if name in cls.SOFT_FACTORS)

    @classmethod
    def _event_confirmed_at(cls, event: dict | None, timeframe: str):
        """When a structure event became known, not when its candle opened.

        Events carry the candle's opening timestamp, but a break is only
        confirmed once that candle closes. Comparing the opening timestamp
        against LTF timestamps let a gap forming *inside* the HTF candle — while
        the break was still unconfirmed — count as having formed after it.

        On a 4h anchor that window is up to four hours of look-ahead.
        """
        if event is None:
            return None
        opened = event["index"]
        duration = cls.TIMEFRAME_DURATIONS.get(timeframe)
        return opened + duration if duration is not None else opened

    @staticmethod
    def _fmt(price: float) -> str:
        """Format a price with enough decimals to stay meaningful.

        A flat 2dp renders XRP as '1.06' and collapses its risk to a single
        cent, which is where the sizing blow-ups came from.
        """
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
        """Callable snapping a price to the symbol's tick size, or None."""
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
        df = df.loc[df.index + duration <= now]
        return df if len(df) >= 50 else None

    @staticmethod
    def _htf_context(df_htf: pd.DataFrame, direction: str) -> tuple:
        """Heavy HTF analysis reused across identical HTF slices in a replay scan."""
        structure_htf = latest_structure_event(df_htf, direction, window=15)
        atr_htf_val = atr(df_htf, period=14).iloc[-1] if len(df_htf) > 14 else 0
        return structure_htf, atr_htf_val

    def _check_direction(self, df_htf: pd.DataFrame, df_ltf: pd.DataFrame, direction: str, tf_htf: str = "15m", tf_ltf: str = "1m", htf_context: tuple | None = None, market_ctx: dict | None = None, quantize=None) -> dict:
        bull_dir = direction == "long"
        quantize = quantize or (lambda price: price)

        if htf_context is not None:
            structure_htf, atr_htf_val = htf_context
        else:
            structure_htf, atr_htf_val = self._htf_context(df_htf, direction)

        structure_ltf = detect_structure(df_ltf, window=15)
        atr_ltf_val = atr(df_ltf, period=14).iloc[-1] if len(df_ltf) > 14 else 0
        fvg_ltf_info = fair_value_gaps(df_ltf, lookback=60)

        # Gate on the raw break so behaviour matches the pre-classification code;
        # the CHOCH / BOS / BREAK distinction is reported, not filtered on, until
        # the backtest says which kinds are worth keeping.
        if bull_dir:
            struct_htf = structure_htf.get(
                "bullish_break",
                structure_htf["bullish_choch"] or structure_htf["bullish_bos"],
            )
            confirm_ltf = structure_ltf["bullish_choch"]
            fvg_below = fvg_ltf_info["bullish_fvgs"]
        else:
            struct_htf = structure_htf.get(
                "bearish_break",
                structure_htf["bearish_choch"] or structure_htf["bearish_bos"],
            )
            confirm_ltf = structure_ltf["bearish_choch"]
            fvg_below = fvg_ltf_info["bearish_fvgs"]

        # 1. HTF structure shift
        reason_htf = None
        if structure_htf["bullish_choch"] if bull_dir else structure_htf["bearish_choch"]:
            reason_htf = f"{tf_htf.upper()} CHOCH {'Bullish' if bull_dir else 'Bearish'}"
        elif structure_htf["bullish_bos"] if bull_dir else structure_htf["bearish_bos"]:
            reason_htf = f"{tf_htf.upper()} BOS {'Bullish' if bull_dir else 'Bearish'}"
        elif struct_htf:
            reason_htf = f"{tf_htf.upper()} level break {'Bullish' if bull_dir else 'Bearish'} (no trend)"

        # 2. 1m CHOCH alignment
        reason_ltf = None
        if confirm_ltf:
            reason_ltf = f"{tf_ltf.upper()} CHOCH {'Bullish' if bull_dir else 'Bearish'} aligned"

        # 3. FVG on 1m
        best_fvg = None
        reason_fvg = None
        # Timed by the event candle's *open*, deliberately.
        #
        # This looks like a cross-timeframe hazard and is not one. _ohlcv_to_df
        # drops the still-forming candle, so an HTF event always comes from a
        # candle that has already closed — there is no look-ahead to fix.
        #
        # Switching to the confirmation time (see _event_confirmed_at) would
        # exclude any LTF gap formed inside the HTF candle. In SMC that gap is
        # usually created *by* the displacement that broke structure, so
        # excluding it would drop the most canonical entry of all. Which
        # convention performs better is an empirical question, not an obvious
        # one: both are exported to the backtest as fvg_after_open and
        # fvg_after_confirm so factor_edge can settle it.
        structure_events = [
            event for event in [structure_htf["event"], structure_ltf["event"]]
            if event is not None and event["direction"] == direction
        ]
        structure_time = max((event["index"] for event in structure_events), default=None)
        structure_confirm_time = max(
            (t for t in (
                self._event_confirmed_at(event, tf)
                for event, tf in ((structure_htf["event"], tf_htf),
                                  (structure_ltf["event"], tf_ltf))
                if event is not None and event["direction"] == direction
            ) if t is not None),
            default=None,
        )
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
                reason_fvg = f"{tf_ltf.upper()} Bullish FVG ${self._fmt(best_fvg['gap_low'])}-${self._fmt(best_fvg['gap_high'])} (fresh)"
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
                reason_fvg = f"{tf_ltf.upper()} Bearish FVG ${self._fmt(best_fvg['gap_low'])}-${self._fmt(best_fvg['gap_high'])} (fresh)"

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
                    reason_ob = f"{'Bullish' if bull_dir else 'Bearish'} OB ${self._fmt(ob_price)} ({dist/atr_htf_val:.1f} ATR)"

        # 5. Breakout candle impulse
        reason_breakout = None
        if is_breakout_candle(df_ltf, direction, lookback=5, vol_multiplier=1.15):
            reason_breakout = f"{tf_ltf.upper()} impulsive + volume spike"
            
        # 6. Liquidity Sweep before CHOCH
        reason_sweep = None
        if structure_time is not None and detect_liquidity_sweep(df_ltf, direction, before=structure_time, window=30):
            reason_sweep = f"{tf_ltf.upper()} Liquidity Sweep before CHOCH"

        # 7. Binance Long/Short 24h (contrarian: crowd against the direction)
        reason_long_short = None
        if market_ctx is not None and market_ctx.get("long_short"):
            ls = market_ctx["long_short"]
            crowd = "long" if ls["long_pct"] > ls["short_pct"] else "short"
            if crowd != direction:
                reason_long_short = (
                    f"Binance Long/Short 24h: {ls['long_pct']:.1f}%L/"
                    f"{ls['short_pct']:.1f}%S (crowded {crowd}, supports {direction})"
                )

        # 8. Liquidation cluster in the direction of travel, near the entry
        reason_cluster = None
        if market_ctx is not None and market_ctx.get("clusters") and best_fvg is not None:
            clusters = market_ctx["clusters"]
            target = clusters["nearest_below"] if bull_dir else clusters["nearest_above"]
            if target is not None and best_fvg["gap_mid"] > 0:
                dist_pct = abs(target["price"] - best_fvg["gap_mid"]) / best_fvg["gap_mid"] * 100.0
                if dist_pct <= self.cluster_proximity_pct:
                    reason_cluster = (
                        f"Liquidation cluster ${self._fmt(target['price'])} "
                        f"({dist_pct:.1f}% dari entry, {target['strength']})"
                    )

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

        tagged = [
            ("structure", reason_htf), ("structure", reason_ltf), ("fvg", reason_fvg),
            ("ob", reason_ob), ("breakout", reason_breakout), ("sweep", reason_sweep),
            ("long_short", reason_long_short), ("cluster", reason_cluster),
        ]
        reasons = [text for _, text in tagged if text]
        confluence = len(reasons)
        soft_hits = self._count_soft(name for name, text in tagged if text)

        if soft_hits < self.min_soft_confluence:
            return {"valid": False,
                    "reason": (f"Soft confluence too low: {soft_hits}/{len(self.SOFT_FACTORS)} "
                               f"(need {self.min_soft_confluence})"),
                    "reasons": reasons, "confluence": confluence, "soft_hits": soft_hits}

        sl = liquidity_inflection(df_ltf, direction, before=best_fvg["index"])
        if sl is None:
            return {"valid": False, "reason": "No confirmed swing before FVG for Stop Loss",
                    "reasons": reasons, "confluence": confluence}

        sl_buffer = atr_ltf_val * 1.5
        if bull_dir:
            sl -= sl_buffer
        else:
            sl += sl_buffer

        # Snap to the exchange tick before measuring risk: the traded prices are
        # what the risk is actually taken on.
        entry = quantize(entry)
        sl = quantize(sl)

        if bull_dir:
            risk = entry - sl
            if risk <= 0:
                return {"valid": False,
                        "reason": f"Invalid SL: entry ${self._fmt(entry)} <= SL ${self._fmt(sl)}",
                        "reasons": reasons, "confluence": confluence}
            tp = quantize(entry + (risk * self.rr_target))
        else:
            risk = sl - entry
            if risk <= 0:
                return {"valid": False,
                        "reason": f"Invalid SL: entry ${self._fmt(entry)} >= SL ${self._fmt(sl)}",
                        "reasons": reasons, "confluence": confluence}
            tp = quantize(entry - (risk * self.rr_target))

        # Cost gate: a stop only a few ticks wide is noise, and round-trip fees
        # eat most of 1R. Reject before the setup ever reaches the journal.
        risk_pct = risk / entry * 100.0
        if risk_pct < self.min_stop_pct:
            return {"valid": False,
                    "reason": (f"Stop too tight vs costs: {risk_pct:.3f}% < {self.min_stop_pct:.3f}% "
                               f"({self.round_trip_cost_pct:.3f}% round-trip x {self.min_cost_multiple:g})"),
                    "reasons": reasons, "confluence": confluence}

        rr = (tp - entry) / risk if bull_dir else (entry - tp) / risk
        # Net of costs, the reward shrinks and the loss grows by the same amount.
        cost = entry * self.round_trip_cost_pct / 100.0
        rr_net = (rr * risk - cost) / (risk + cost)

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
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "rr": round(rr, 2),
            "rr_net": round(rr_net, 2),
            "risk": risk,
            "risk_pct": round(risk_pct, 3),
            "confluence": confluence,
            "soft_hits": soft_hits,
            "reasons": reasons,
            "timestamp": df_ltf.index[-1],
            "structure_htf": structure_htf["event"],
            "structure_ltf": structure_ltf["event"],
            "fvg_timestamp": best_fvg["index"],
            # Measured, not gated on: would this setup still qualify under the
            # stricter rule that the gap must form after the HTF candle closes?
            "fvg_after_confirm": bool(
                structure_confirm_time is None
                or best_fvg["index"] >= structure_confirm_time
            ),
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

        market_ctx = None
        if self.long_short_enabled or self.liquidation_enabled:
            market_ctx = {}
            if self.long_short_enabled:
                market_ctx["long_short"] = long_short_24h(
                    sym, self.market_cache_minutes, self.long_short_source
                )
            if self.liquidation_enabled:
                market_ctx["clusters"] = estimate_liquidation_clusters(df_ltf, self.liquidation_leverage)

        quantize = self._quantizer(sym)

        best = None
        for direction in ["long", "short"]:
            result = self._check_direction(df_htf, df_ltf, direction, tf_htf, tf_ltf,
                                           market_ctx=market_ctx, quantize=quantize)
            if result["valid"]:
                result["pair"] = sym
                result["base"] = base
                result["tf_combo"] = f"{tf_htf}/{tf_ltf}"
                result["tf_htf"] = tf_htf
                result["tf_ltf"] = tf_ltf
                if best is None or self._rank(result) > self._rank(best):
                    best = result
        if best is not None:
            self._attach_market_context(best, df_ltf)
        return best

    def _attach_market_context(self, setup: dict, df_ltf: pd.DataFrame) -> None:
        """Attach observed market data to a valid setup, for the reader to judge.

        This is deliberately *context*, not confluence: none of it gates or
        scores the setup. Aegis reports; the decision is the reader's, and a
        decision needs the state of the market, not just the pattern that fired.

        Only called once a setup is valid — 21 pair/combo evaluations per scan
        would otherwise burn the REST budget on order book snapshots nobody
        reads.
        """
        symbol = setup["pair"]
        context: dict = {}

        oi_now = fetch_open_interest(symbol)
        if oi_now:
            context["open_interest"] = oi_now["open_interest"]
            series = PositioningSeries(symbol, "open_interest", "4h")
            if len(series):
                context["oi_change_24h_pct"] = series.change_pct(
                    int(pd.Timestamp.now(tz="UTC").timestamp() * 1000), 24 * 3600 * 1000
                )

        funding = PositioningSeries(symbol, "funding_rate", "8h")
        if len(funding):
            now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
            context["funding_bp"] = funding.as_of(now_ms)
            context["funding_z"] = funding.zscore_as_of(now_ms)

        volume = volume_context(df_ltf)
        if volume:
            context["volume_ratio"] = volume["ratio"]

        walls = fetch_liquidity_walls(symbol, setup["entry"])
        if walls:
            context["liquidity"] = walls

        setup["context"] = context

    @staticmethod
    def _rank(setup: dict) -> tuple:
        """Rank competing long/short setups on the same pair and combo.

        Freshness leads, not confluence. `rr` is always `rr_target` by
        construction so it carries no information, and confluence turned out to
        be directionally biased: perpetual crowds sit net long essentially all
        the time (measured 1309/1309 observations above 50% long across 7
        pairs), so the contrarian factor adds +1 to every short and never to a
        long. Ranking on confluence therefore handed almost every tie to the
        short side regardless of setup quality.
        """
        return (setup["fvg_timestamp"], setup["confluence"], setup["rr_net"])

    def _journal_signal(self, setup: dict) -> None:
        """Persist a valid setup to the signal journal (non-fatal on errors)."""
        try:
            import db
            entry = dict(setup)
            entry["signal_time"] = setup["timestamp"].isoformat()
            if db.save_signal(entry):
                print(f"  journal: {setup['pair']} {setup['direction']} "
                      f"entry ${self._fmt(setup['entry'])} @ {entry['signal_time']}")
            db.log_signal(setup)
        except Exception as e:
            print(f"  journal error: {e}")

    def analyze(self) -> list[dict]:
        results = []
        combinations = [("15m", "1m"), ("1h", "5m"), ("4h", "15m")]
        for sym in self.pairs:
            for tf_htf, tf_ltf in combinations:
                try:
                    setup = self.analyze_pair(sym, tf_htf, tf_ltf)
                    if setup:
                        results.append(setup)
                        self._journal_signal(setup)
                except Exception as e:
                    print(f"  ERROR {sym} ({tf_htf}/{tf_ltf}): {e}")
        return results
