"""Track live signals from publication to resolution.

Aegis places no orders, so nothing was ever watching what happened to a signal
after it was announced. This closes that loop using price alone:

    PENDING      published, price has not reached entry yet
      -> TRIGGERED    price touched the entry
      -> INVALIDATED  price hit the stop before ever reaching entry
      -> EXPIRED      the setup went stale unfilled
    TRIGGERED
      -> CLOSED       take profit or stop reached

The result is real outcome data — fill rate, win rate, realised R — recorded
without a single order and without an API key. Reading public prices is all it
takes to know whether a setup worked.

Checks run on closed candles only, so a signal is never resolved by a wick that
the strategy itself would not have seen.
"""
import logging
from datetime import datetime, timezone

import db
import execution

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("PENDING", "TRIGGERED")


def _hit(price: float, level: float, direction: str, above: bool) -> bool:
    """Whether price reached a level, given which side counts as reaching it."""
    return price >= level if above else price <= level


def evaluate(signal: dict, price: float, ttl_minutes: int = 15) -> tuple[str, str] | None:
    """Return (new_status, reason) for a signal, or None if nothing changed.

    Pure: takes a price and returns a decision, so the state machine can be
    tested without touching the database or the network.
    """
    direction = signal["direction"]
    long = direction == "long"
    status = signal["status"]

    if status == "PENDING":
        # Order matters. A stop reached before entry means the structure the
        # setup rested on is gone — reporting that as a loss would be wrong,
        # because the entry never happened.
        if _hit(price, signal["sl"], direction, above=not long):
            return "INVALIDATED", "SL tersentuh sebelum entry"
        if _hit(price, signal["entry"], direction, above=not long):
            return "TRIGGERED", "harga menyentuh entry"
        age = _age_minutes(signal.get("timestamp"))
        if age is not None and age > ttl_minutes:
            return "EXPIRED", f"tidak tersentuh dalam {ttl_minutes} menit"
        return None

    if status == "TRIGGERED":
        if _hit(price, signal["sl"], direction, above=not long):
            return "CLOSED", "SL"
        if _hit(price, signal["tp"], direction, above=long):
            return "CLOSED", "TP"
        return None

    return None


def _age_minutes(timestamp) -> float | None:
    if timestamp is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 60.0


def progress_r(signal: dict, price: float) -> float | None:
    """How far the move has gone, in R, measured from the entry."""
    reference = signal.get("fill_price") or signal["entry"]
    risk = abs(reference - signal["sl"])
    if risk <= 0:
        return None
    moved = (price - reference) if signal["direction"] == "long" else (reference - price)
    return moved / risk


def check_all(ttl_minutes: int = 15) -> dict:
    """Advance every active signal against current price.

    Returns {"valid": [...], "invalid": [...]} for the heartbeat to render.
    """
    valid, invalid = [], []
    prices: dict[str, float] = {}

    for status in ACTIVE_STATUSES:
        for signal in db.fetch_trade_journal(status):
            pair = signal["pair"]
            if pair not in prices:
                fetched = execution.fetch_price(pair)
                if fetched is None:
                    logger.warning(f"{pair}: harga tidak tersedia, sinyal dilewati")
                    continue
                prices[pair] = fetched
            price = prices[pair]

            decision = evaluate(signal, price, ttl_minutes)
            if decision is None:
                valid.append({**signal, "price": price,
                              "progress_r": progress_r(signal, price)})
                continue

            new_status, reason = decision
            if new_status == "TRIGGERED":
                db.record_fill(signal["id"], signal["entry"])
                db.update_trade_status(signal["id"], "TRIGGERED")
                valid.append({**signal, "status": "TRIGGERED", "price": price,
                              "progress_r": 0.0, "note": reason})
                logger.info(f"Sinyal {signal['id']} {pair}: {reason}")
                continue

            if new_status == "CLOSED":
                realized = db.record_exit(signal["id"], price, reason)
                invalid.append({**signal, "status": "CLOSED", "price": price,
                                "reason": reason, "realized_r": realized})
                logger.info(f"Sinyal {signal['id']} {pair}: ditutup {reason} "
                            f"({realized:+.2f}R)" if realized is not None else reason)
                continue

            db.update_trade_status(signal["id"], new_status)
            invalid.append({**signal, "status": new_status, "price": price,
                            "reason": reason})
            logger.info(f"Sinyal {signal['id']} {pair}: {new_status} — {reason}")

    return {"valid": valid, "invalid": invalid}
