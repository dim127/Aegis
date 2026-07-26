import sqlite3
import os
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DB_DIR, "aegis_cache.db")


def _ensure_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
    conn.close()


def get_cached_ohlcv(symbol: str, interval: str, max_age_minutes: int = 5) -> Optional[pd.DataFrame]:
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
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
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
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
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.utcnow() - timedelta(seconds=max_age_seconds)).isoformat()
    row = conn.execute(
        "SELECT price FROM price_cache WHERE symbol = ? AND updated_at >= ?",
        (symbol, cutoff),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def save_price(symbol: str, price: float):
    _ensure_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO price_cache VALUES (?, ?, ?)",
        (symbol, price, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
