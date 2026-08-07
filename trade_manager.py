"""Trade manager: executes journaled SMC setups on Binance futures.

Reads PENDING rows from the trade_journal (written by the scanner), places a
limit order at the FVG midpoint plus attached SL/TP market-stop orders, then
monitors until the position closes. Only acts when Binance API keys are set
in aegis_config.json; otherwise it logs and idles.

Usage:
    ./venv/bin/python3 trade_manager.py --once
    ./venv/bin/python3 trade_manager.py --interval 60
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

import db
import execution
from scan_lock import ScanLock, TRADE_LOCK_PATH

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("trade_manager")

CONFIG_PATH = Path(__file__).resolve().parent / "aegis_config.json"

DEFAULT_RISK = {
    "enabled": True,
    "capital": 1000.0,
    "risk_percent": 1.0,
    "leverage": 1.0,
    "max_notional_pct": 300.0,
    "max_concurrent_positions": 3,
}
FILL_WINDOW_MINUTES = 60
SIGNAL_TTL_MINUTES = 15


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open() as f:
        return json.load(f)


def load_risk_config() -> dict:
    return {**DEFAULT_RISK, **_load_config().get("risk", {})}


def load_fill_window() -> int:
    return int(_load_config().get("fill_window_minutes", FILL_WINDOW_MINUTES))


def load_signal_ttl() -> int:
    return int(_load_config().get("signal_ttl_minutes", SIGNAL_TTL_MINUTES))


def _parse_time(value) -> datetime | None:
    """Coerce a ccxt/SQLite timestamp to an aware datetime.

    ccxt returns order['timestamp'] as epoch milliseconds (an int); SQLite
    returns 'YYYY-MM-DD HH:MM:SS' text. Subtracting an int from a datetime is
    what previously raised TypeError and aborted the whole monitor pass.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _age_minutes(value) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0


def compute_amount(trade: dict, risk: dict) -> float:
    size = execution.calculate_position_size(
        risk["capital"],
        risk["risk_percent"],
        trade["entry"],
        trade["sl"],
        risk.get("max_notional_pct", 300.0),
    )
    if size <= 0:
        return 0.0
    size = execution.quantize_amount(trade["pair"], size)
    if not execution.meets_exchange_minimums(trade["pair"], size, trade["entry"]):
        return 0.0
    return max(0.0, size)


def _account_capital(risk: dict) -> float:
    """Live equity when available, else the configured capital as a fallback."""
    equity = execution.fetch_equity()
    if equity is None or equity <= 0:
        return float(risk["capital"])
    return equity


def _cancel_stops(trade: dict) -> None:
    """Cancel any resting protective orders for a trade leaving PLACED/OPEN."""
    for key in ("sl_order_id", "tp_order_id"):
        order_id = trade.get(key)
        if order_id:
            execution.cancel_order(order_id, trade["pair"])


def place_trade(trade: dict, risk: dict | None = None) -> bool:
    if not execution.has_credentials():
        logger.info("No Binance credentials — skipping placement (journal only).")
        return False
    risk = risk if risk is not None else load_risk_config()
    amount = compute_amount(trade, risk)
    if amount <= 0:
        db.update_trade_status(trade["id"], "CANCELLED")
        logger.warning(f"Trade {trade['id']}: invalid amount, cancelled")
        return False
    side = "buy" if trade["direction"] == "long" else "sell"
    try:
        order = execution.place_limit_order(side, trade["pair"], amount, trade["entry"])
    except Exception as e:
        logger.error(f"Trade {trade['id']} {trade['pair']}: placement failed ({e})")
        return False
    if order is None or not order.get("id"):
        logger.error(f"Trade {trade['id']} {trade['pair']}: no order id returned")
        return False
    # Protective orders are attached on fill, not here — a reduce-only stop
    # placed against a position that does not exist yet is left orphaned when
    # the entry expires, and can later close an unrelated position.
    db.update_trade_status(trade["id"], "PLACED", order["id"])
    logger.info(
        f"Trade {trade['id']}: {side.upper()} LIMIT {amount} {trade['pair']} "
        f"@ {trade['entry']} | SL {trade['sl']} | TP {trade['tp']} (entry {order['id']})"
    )
    return True


def _attach_stops(trade: dict, amount: float) -> None:
    sl_order, tp_order = execution.place_stop_orders(
        trade["pair"], amount, trade["direction"], trade["sl"], trade["tp"]
    )
    db.record_stop_orders(
        trade["id"],
        sl_order.get("id") if sl_order else None,
        tp_order.get("id") if tp_order else None,
    )
    logger.info(
        f"Trade {trade['id']} {trade['pair']}: stops attached "
        f"(sl {sl_order and sl_order.get('id')}, tp {tp_order and tp_order.get('id')})"
    )


def monitor_placed(trade: dict, fill_window_minutes: int) -> None:
    if not execution.has_credentials():
        return
    if not trade.get("order_id"):
        # Never revert to PENDING: it would be placed again next pass.
        db.update_trade_status(trade["id"], "CANCELLED")
        logger.warning(f"Trade {trade['id']}: PLACED without an order id, cancelled")
        return
    order = execution.fetch_order(trade["order_id"], trade["pair"])
    if order is None:
        return
    status = str(order.get("status", "")).lower()

    if status in ("closed", "filled"):
        fill_price = order.get("average") or order.get("price") or trade["entry"]
        filled = float(order.get("filled") or order.get("amount") or 0)
        db.record_fill(trade["id"], float(fill_price))
        db.update_trade_status(trade["id"], "OPEN")
        logger.info(f"Trade {trade['id']} {trade['pair']}: entry filled @ {fill_price}")
        if filled > 0:
            _attach_stops(trade, filled)
        return

    if status in ("canceled", "cancelled", "expired", "rejected"):
        _cancel_stops(trade)
        db.update_trade_status(trade["id"], "CANCELLED")
        return

    age_minutes = _age_minutes(order.get("timestamp"))
    if age_minutes is not None and age_minutes > fill_window_minutes:
        execution.cancel_order(trade["order_id"], trade["pair"])
        _cancel_stops(trade)
        db.update_trade_status(trade["id"], "CANCELLED")
        logger.info(f"Trade {trade['id']} {trade['pair']}: expired after {fill_window_minutes}m")


def monitor_open(trade: dict) -> None:
    if not execution.has_credentials():
        return
    positions = execution.fetch_positions()
    if positions is None:
        # Unknown, not flat. Marking CLOSED here would orphan a live position
        # and free the pair for a second, stacked entry.
        logger.warning(f"Trade {trade['id']}: position check failed, leaving OPEN")
        return

    side = trade["direction"]
    for position in positions:
        if (position.get("symbol") == trade["pair"]
                and position.get("side") == side
                and float(position.get("contracts") or 0) > 0):
            return

    # Flat on the exchange: the SL or TP filled. Whichever it was, the other is
    # still resting and must go.
    _cancel_stops(trade)
    exit_price = execution.fetch_price(trade["pair"]) or trade["entry"]
    reference = trade.get("fill_price") or trade["entry"]
    hit_tp = (exit_price >= trade["tp"]) if side == "long" else (exit_price <= trade["tp"])
    realized_r = db.record_exit(
        trade["id"], float(exit_price), "TP" if hit_tp else "SL"
    )
    logger.info(
        f"Trade {trade['id']} {trade['pair']}: closed @ {exit_price} "
        f"(entry {reference}, {realized_r:+.2f}R)" if realized_r is not None
        else f"Trade {trade['id']} {trade['pair']}: closed @ {exit_price}"
    )


def _active_pairs() -> set[str]:
    pairs = {t["pair"] for t in db.fetch_trade_journal("PLACED")}
    pairs.update(t["pair"] for t in db.fetch_trade_journal("OPEN"))
    return pairs


def expire_stale_signals(ttl_minutes: int) -> int:
    """Drop PENDING rows whose setup has gone stale.

    fill_window_minutes only starts counting after placement, so without this a
    signal generated hours ago is still placed at a price and structure that no
    longer exist.
    """
    expired = 0
    for trade in db.fetch_trade_journal("PENDING"):
        age = _age_minutes(trade.get("timestamp"))
        if age is not None and age > ttl_minutes:
            db.update_trade_status(trade["id"], "EXPIRED")
            logger.info(
                f"Trade {trade['id']} {trade['pair']}: expired unplaced "
                f"({age:.0f}m old, ttl {ttl_minutes}m)"
            )
            expired += 1
    return expired


def reconcile() -> None:
    """Match exchange state against the journal before placing anything.

    A crash between place_limit_order and update_trade_status leaves a real
    order on the exchange with the journal still PENDING, which would place a
    duplicate on restart.
    """
    if not execution.has_credentials():
        return
    pending = db.fetch_trade_journal("PENDING")
    if not pending:
        return
    for pair in {t["pair"] for t in pending}:
        open_orders = execution.fetch_open_orders(pair)
        for order in open_orders:
            if order.get("reduceOnly"):
                continue
            price = float(order.get("price") or 0)
            for trade in pending:
                if trade["pair"] != pair or trade["status"] != "PENDING":
                    continue
                if price and abs(price - trade["entry"]) / trade["entry"] < 0.0005:
                    db.update_trade_status(trade["id"], "PLACED", order["id"])
                    trade["status"] = "PLACED"
                    logger.warning(
                        f"Trade {trade['id']} {pair}: adopted orphaned order "
                        f"{order['id']} @ {price}"
                    )
                    break


def run_once() -> None:
    risk = load_risk_config()
    if not risk.get("enabled", True):
        logger.warning("risk.enabled is false — placement halted, monitoring only.")

    fill_window_minutes = load_fill_window()
    expire_stale_signals(load_signal_ttl())

    active_pairs = _active_pairs()
    max_positions = int(risk.get("max_concurrent_positions", 3))

    if risk.get("enabled", True):
        capital = _account_capital(risk)
        sizing = {**risk, "capital": capital}
        for trade in db.fetch_trade_journal("PENDING"):
            if len(active_pairs) >= max_positions:
                logger.info(
                    f"Trade {trade['id']} {trade['pair']}: skipped — "
                    f"{len(active_pairs)}/{max_positions} concurrent positions"
                )
                continue
            if trade["pair"] in active_pairs:
                logger.info(
                    f"Trade {trade['id']} {trade['pair']}: skipped — "
                    f"position already active on this pair"
                )
                continue
            if place_trade(trade, sizing):
                active_pairs.add(trade["pair"])

    for trade in db.fetch_trade_journal("PLACED"):
        monitor_placed(trade, fill_window_minutes)
    for trade in db.fetch_trade_journal("OPEN"):
        monitor_open(trade)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute journaled SMC setups.")
    parser.add_argument("--once", action="store_true", help="run a single pass")
    parser.add_argument("--interval", type=int, default=60, help="seconds between passes")
    parser.add_argument("--live", action="store_true",
                        help="required to trade real money on Binance mainnet")
    args = parser.parse_args()

    mode = execution.environment_name()
    if execution.is_testnet():
        logger.info(f"trade_manager running in {mode} mode")
        logger.info("Using TESTNET futures + isolated test DBs (aegis_cache_testnet.db)")
    elif not args.live:
        logger.error(
            "Refusing to run against LIVE Binance without --live. "
            "Set exchange.binance.testnet = true, or pass --live to trade real money."
        )
        sys.exit(1)
    else:
        logger.warning("Using LIVE Binance futures. Orders are REAL.")

    with ScanLock(TRADE_LOCK_PATH) as lock:
        if not lock.acquired:
            logger.error("Another trade_manager is already running — exiting.")
            sys.exit(1)

        # Once at startup only: this is about surviving a crash mid-placement,
        # and it costs a REST call per pending pair.
        reconcile()

        if args.once:
            run_once()
            return
        while True:
            try:
                run_once()
            except Exception as e:
                logger.exception(f"Pass failed: {e}")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
