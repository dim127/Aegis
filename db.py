import sqlite3
import os
import json
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Optional

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DB_DIR, "aegis_cache.db")
SIGNALS_DB_PATH = os.path.join(os.path.dirname(__file__), "aegis_signals.db")


def _active_paths() -> tuple[str, str]:
    """Return (cache_db_path, signals_db_path).

    There is a single set of databases: Aegis reads public data and records the
    signals it produced, so there are no per-account environments to keep apart.
    Module attributes are read at call time so tests can redirect them.
    """
    return DB_PATH, SIGNALS_DB_PATH


def _ensure_db(cache_db: str):  # type: ignore[no-untyped-def]
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(cache_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv_cache (
            symbol TEXT,
            interval TEXT,
            timestamp INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (symbol, interval, timestamp)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            symbol TEXT PRIMARY KEY,
            price REAL,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            pair TEXT,
            tf_combo TEXT,
            direction TEXT,
            entry_price REAL,
            sl REAL,
            tp REAL,
            rr REAL,
            status TEXT DEFAULT 'PENDING'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_metrics (
            symbol TEXT,
            metric TEXT,
            payload TEXT,
            updated_at REAL,
            PRIMARY KEY (symbol, metric)
        )
    """)
    # Timestamped positioning history (long/short ratio, open interest). Unlike
    # market_metrics, which holds one TTL-cached snapshot per symbol, this keeps
    # the series so a backtest can look up the value as of a past candle.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positioning_history (
            symbol TEXT,
            metric TEXT,
            period TEXT,
            timestamp INTEGER,
            value REAL,
            extra TEXT,
            PRIMARY KEY (symbol, metric, period, timestamp)
        )
    """)
    conn.commit()
    # Idempotent migrations: SQLite has no ADD COLUMN IF NOT EXISTS, so each is
    # attempted and the "duplicate column name" error swallowed.
    # Outcome columns: a signal is only as good as what happened next, so the
    # journal records whether the entry was reached and how it resolved.
    for column in (
        "fill_price REAL",
        "fill_time TEXT",
        "exit_price REAL",
        "exit_time TEXT",
        "exit_reason TEXT",
        "fees_paid REAL",
        "realized_r REAL",
    ):
        try:
            conn.execute(f"ALTER TABLE trade_journal ADD COLUMN {column}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.close()


def get_cached_ohlcv(symbol: str, interval: str, max_age_minutes: int = 5) -> Optional[pd.DataFrame]:
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    cutoff = int((datetime.utcnow() - timedelta(minutes=max_age_minutes)).timestamp())
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume FROM ohlcv_cache "
        "WHERE symbol = ? AND interval = ? AND timestamp >= ? "
        "ORDER BY timestamp ASC",
        conn,
        params=(symbol, interval, cutoff),
    )
    conn.close()
    if df.empty:
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df.set_index("timestamp", inplace=True)
    return df


def save_ohlcv(symbol: str, interval: str, df: pd.DataFrame):
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    rows = []
    for idx, row in df.iterrows():
        ts = int(idx.timestamp())
        rows.append(
            (
                symbol,
                interval,
                ts,
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                float(row["Volume"]),
            )
        )
    conn.executemany(
        "INSERT OR REPLACE INTO ohlcv_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_cached_price(symbol: str, max_age_seconds: int = 30) -> Optional[float]:
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    cutoff = (datetime.utcnow() - timedelta(seconds=max_age_seconds)).isoformat()
    row = conn.execute(
        "SELECT price FROM price_cache WHERE symbol = ? AND updated_at >= ?",
        (symbol, cutoff),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def save_price(symbol: str, price: float):
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    conn.execute(
        "INSERT OR REPLACE INTO price_cache VALUES (?, ?, ?)",
        (symbol, price, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


SIGNALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_time TEXT,
    pair TEXT,
    tf_htf TEXT,
    tf_ltf TEXT,
    direction TEXT,
    entry REAL,
    sl REAL,
    tp REAL,
    risk REAL,
    rr REAL,
    confluence INTEGER,
    reasons TEXT,
    created_at TEXT
)
"""


def _ensure_signals_db(signals_db: str):  # type: ignore[no-untyped-def]
    conn = sqlite3.connect(signals_db)
    conn.execute(SIGNALS_SCHEMA)
    conn.commit()
    conn.close()


def save_signal(signal: dict, dedup_minutes: int = 60) -> bool:
    """Persist a valid SMC setup to the signal journal.

    Deduplicates repeated scans: a signal for the same pair / timeframes /
    direction / entry within `dedup_minutes` is not inserted twice.
    Reasons for the dedup window.
    Returns True when a new row was inserted.
    """
    _, signals_db = _active_paths()
    _ensure_signals_db(signals_db)
    conn = sqlite3.connect(signals_db)
    reasons = signal.get("reasons", "")
    if isinstance(reasons, list):
        reasons = "; ".join(str(r) for r in reasons)
    cutoff = (datetime.utcnow() - timedelta(minutes=dedup_minutes)).isoformat()
    duplicate = conn.execute(
        "SELECT 1 FROM signals WHERE pair = ? AND tf_htf = ? AND tf_ltf = ? "
        "AND direction = ? AND entry = ? AND signal_time >= ?",
        (signal["pair"], signal["tf_htf"], signal["tf_ltf"],
         signal["direction"], signal["entry"], cutoff),
    ).fetchone()
    if duplicate:
        conn.close()
        return False
    conn.execute(
        "INSERT INTO signals (signal_time, pair, tf_htf, tf_ltf, direction, "
        "entry, sl, tp, risk, rr, confluence, reasons, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (signal.get("signal_time", ""), signal["pair"], signal["tf_htf"],
         signal["tf_ltf"], signal["direction"], signal["entry"], signal["sl"],
         signal["tp"], signal["risk"], signal["rr"], signal["confluence"],
         reasons, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return True


def fetch_signals(limit: int = 100) -> list[dict]:
    _, signals_db = _active_paths()
    _ensure_signals_db(signals_db)
    conn = sqlite3.connect(signals_db)
    rows = conn.execute(
        "SELECT signal_time, pair, tf_htf, tf_ltf, direction, entry, sl, tp, "
        "rr, confluence FROM signals ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    columns = ["signal_time", "pair", "tf_htf", "tf_ltf", "direction",
               "entry", "sl", "tp", "rr", "confluence"]
    return [dict(zip(columns, row)) for row in rows]

def expire_stale_signals(ttl_minutes: int = 15) -> int:
    """Retire PENDING signals older than the TTL. Returns how many were retired.

    A setup describes a specific moment: an unmitigated FVG, a fresh structure
    break, price not yet at entry. Hours later none of that is still true, so a
    stale PENDING row is not a live signal — it is a record that should be
    closed out.

    This also keeps the dedup below honest. Dedup suppresses a repeat signal
    while one is already PENDING for the same pair/combo/direction; without
    expiry that suppression becomes permanent and the journal silently stops
    recording anything new for that combination.
    """
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = sqlite3.connect(cache_db)
    cursor = conn.execute(
        "UPDATE trade_journal SET status = 'EXPIRED' "
        "WHERE status = 'PENDING' AND timestamp < ?",
        (cutoff,),
    )
    expired = cursor.rowcount or 0
    conn.commit()
    conn.close()
    return expired


def log_signal(setup: dict, ttl_minutes: int = 15):
    """Queue a valid setup as a PENDING journal row (deduplicated).

    Stale rows are retired first so dedup compares against signals that are
    still live, not against history.
    """
    expire_stale_signals(ttl_minutes)
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    entry_price = setup.get("entry", 0.0)
    # Dedup on the setup, not the price. Entry is an FVG midpoint that drifts a
    # little every scan, so an exact-price match let the same setup queue six
    # times in 40 minutes.
    duplicate = conn.execute(
        "SELECT 1 FROM trade_journal WHERE pair = ? AND tf_combo = ? "
        "AND direction = ? AND status = 'PENDING'",
        (setup.get("pair", ""), setup.get("tf_combo", ""),
         setup.get("direction", "")),
    ).fetchone()
    if duplicate:
        conn.close()
        return False
    conn.execute('''
        INSERT INTO trade_journal 
        (pair, tf_combo, direction, entry_price, sl, tp, rr, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        setup.get("pair", ""),
        setup.get("tf_combo", ""),
        setup.get("direction", ""),
        entry_price,
        setup.get("sl", 0.0),
        setup.get("tp", 0.0),
        setup.get("rr", 0.0),
        "PENDING"
    ))
    conn.commit()
    conn.close()
    return True


def fetch_trade_journal(status: str = "PENDING") -> list[dict]:
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    rows = conn.execute(
        "SELECT id, timestamp, pair, tf_combo, direction, entry_price, sl, tp, rr, "
        "status, fill_price, exit_price, exit_reason, realized_r "
        "FROM trade_journal WHERE status = ? ORDER BY id ASC",
        (status,),
    ).fetchall()
    conn.close()
    columns = ["id", "timestamp", "pair", "tf_combo", "direction", "entry", "sl", "tp",
               "rr", "status", "fill_price", "exit_price", "exit_reason", "realized_r"]
    return [dict(zip(columns, row)) for row in rows]


def get_market_metric(symbol: str, metric: str, max_age_minutes: int = 60) -> Optional[dict]:
    """Read a cached market metric if it is newer than max_age_minutes."""
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    row = conn.execute(
        "SELECT payload, updated_at FROM market_metrics WHERE symbol = ? AND metric = ?",
        (symbol, metric),
    ).fetchone()
    conn.close()
    if not row:
        return None
    age_seconds = time.time() - row[1]
    if age_seconds > max_age_minutes * 60:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None


def set_market_metric(symbol: str, metric: str, payload: dict):
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    conn.execute(
        "INSERT OR REPLACE INTO market_metrics (symbol, metric, payload, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (symbol, metric, json.dumps(payload), time.time()),
    )
    conn.commit()
    conn.close()


def save_positioning_history(symbol: str, metric: str, period: str, rows: list[dict]) -> int:
    """Store a positioning series. Rows need `timestamp` (ms) and `value`."""
    if not rows:
        return 0
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    conn.executemany(
        "INSERT OR REPLACE INTO positioning_history "
        "(symbol, metric, period, timestamp, value, extra) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (symbol, metric, period, int(r["timestamp"]), float(r["value"]),
             json.dumps(r.get("extra")) if r.get("extra") is not None else None)
            for r in rows
        ],
    )
    conn.commit()
    conn.close()
    return len(rows)


def load_positioning_history(symbol: str, metric: str, period: str) -> list[tuple]:
    """Return [(timestamp_ms, value), ...] ascending, for as-of lookups."""
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    rows = conn.execute(
        "SELECT timestamp, value FROM positioning_history "
        "WHERE symbol = ? AND metric = ? AND period = ? ORDER BY timestamp ASC",
        (symbol, metric, period),
    ).fetchall()
    conn.close()
    return rows


def positioning_coverage(symbol: str, metric: str, period: str) -> dict:
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    row = conn.execute(
        "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM positioning_history "
        "WHERE symbol = ? AND metric = ? AND period = ?",
        (symbol, metric, period),
    ).fetchone()
    conn.close()
    return {"rows": row[0] or 0, "first": row[1], "last": row[2]}


def record_fill(trade_id: int, fill_price: float, fill_time: str | None = None):
    """Record that price reached the signal's entry, and at what level."""
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    fill_time = fill_time or datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(cache_db)
    conn.execute(
        "UPDATE trade_journal SET fill_price = ?, fill_time = ? WHERE id = ?",
        (fill_price, fill_time, trade_id),
    )
    conn.commit()
    conn.close()


def record_exit(trade_id: int, exit_price: float, exit_reason: str,
                fees_paid: float = 0.0, exit_time: str | None = None):
    """Close out a trade and compute its realized R.

    R is measured against the actual fill where one was recorded, so slippage on
    entry is reflected in the result rather than hidden.
    """
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    exit_time = exit_time or datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(cache_db)
    row = conn.execute(
        "SELECT direction, entry_price, sl, fill_price FROM trade_journal WHERE id = ?",
        (trade_id,),
    ).fetchone()

    realized_r = None
    if row:
        direction, entry_price, sl, fill_price = row
        reference = fill_price if fill_price else entry_price
        if reference is not None and sl is not None:
            risk = abs(reference - sl)
            if risk > 0:
                pnl = (exit_price - reference) if direction == "long" else (reference - exit_price)
                realized_r = (pnl - fees_paid) / risk

    conn.execute(
        "UPDATE trade_journal SET status = 'CLOSED', exit_price = ?, exit_time = ?, "
        "exit_reason = ?, fees_paid = ?, realized_r = ? WHERE id = ?",
        (exit_price, exit_time, exit_reason, fees_paid, realized_r, trade_id),
    )
    conn.commit()
    conn.close()
    return realized_r


def performance_summary() -> dict:
    """Aggregate realized results — the answer to 'how is the bot doing?'."""
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    rows = conn.execute(
        "SELECT realized_r FROM trade_journal "
        "WHERE status = 'CLOSED' AND realized_r IS NOT NULL"
    ).fetchall()
    conn.close()

    results = [r[0] for r in rows]
    if not results:
        return {"trades": 0, "wins": 0, "win_rate": 0.0, "expectancy_r": 0.0, "total_r": 0.0}
    wins = [r for r in results if r > 0]
    return {
        "trades": len(results),
        "wins": len(wins),
        "win_rate": len(wins) / len(results) * 100.0,
        "expectancy_r": sum(results) / len(results),
        "total_r": sum(results),
    }


def update_trade_status(trade_id: int, status: str):
    """Move a signal through PENDING -> TRIGGERED -> CLOSED / EXPIRED."""
    cache_db, _ = _active_paths()
    _ensure_db(cache_db)
    conn = sqlite3.connect(cache_db)
    conn.execute("UPDATE trade_journal SET status = ? WHERE id = ?", (status, trade_id))
    conn.commit()
    conn.close()
