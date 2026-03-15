"""
cache/db.py — Thread-safe SQLite TTL cache layer.

All downstream fetchers (yfinance, FRED, EDGAR, Schwab) write to and read
from this cache before hitting external APIs.

Database file: vrp_cache.db in the project root.
"""
from __future__ import annotations

import functools
import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
TTL: dict[str, int] = {
    "ohlcv_history": 3600,
    "options_chain_live": 900,
    "options_chain_yf": 1800,
    "fundamentals": 86400,
    "fred_rates": 21600,
    "earnings_dates": 43200,
}

# Default DB path: project root / vrp_cache.db
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "vrp_cache.db"

_DDL = """
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    value       BLOB NOT NULL,
    fetched_at  REAL NOT NULL,
    ttl_seconds INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetched_at ON cache(fetched_at);

CREATE TABLE IF NOT EXISTS garch_params (
    ticker      TEXT PRIMARY KEY,
    params      BLOB NOT NULL,
    baseline_std REAL NOT NULL,
    fitted_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rv_forecast_accuracy (
    ticker          TEXT NOT NULL,
    model           TEXT NOT NULL,
    forecast        REAL,
    actual_rv       REAL,
    forecast_date   TEXT NOT NULL,
    PRIMARY KEY (ticker, model, forecast_date)
);

CREATE TABLE IF NOT EXISTS portfolio_nav_history (
    date        TEXT PRIMARY KEY,
    nav         REAL NOT NULL,
    peak_nav    REAL NOT NULL,
    drawdown_pct REAL NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    structure       TEXT NOT NULL,
    short_strike    REAL,
    long_strike     REAL,
    expiration_date TEXT,
    contracts       INTEGER DEFAULT 1,
    entry_credit    REAL,
    entry_price     REAL,
    entry_date      TEXT,
    sector          TEXT DEFAULT 'Unknown',
    notes           TEXT,
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_greeks (
    date             TEXT PRIMARY KEY,
    total_delta      REAL,
    total_vega       REAL,
    total_theta      REAL,
    total_gamma      REAL,
    theta_efficiency REAL,
    updated_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_results (
    run_id          TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    entry_date      TEXT NOT NULL,
    signal_score    REAL,
    structure       TEXT,
    strike          REAL,
    expiration      TEXT,
    actual_pnl_pct  REAL,
    win             INTEGER,
    PRIMARY KEY (run_id, ticker, entry_date)
);

CREATE TABLE IF NOT EXISTS trade_outcomes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    entry_date          TEXT NOT NULL,
    exit_date           TEXT,
    signal_snapshot     BLOB,
    realized_profit_pct REAL,
    structure           TEXT,
    created_at          REAL NOT NULL
);
"""


class CacheDB:
    """Thread-safe SQLite key-value store with per-entry TTL."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path if db_path is not None else _DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Serialize *value* with pickle and store it under *key*."""
        blob = pickle.dumps(value)
        fetched_at = time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cache (key, value, fetched_at, ttl_seconds)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value       = excluded.value,
                        fetched_at  = excluded.fetched_at,
                        ttl_seconds = excluded.ttl_seconds
                    """,
                    (key, blob, fetched_at, ttl_seconds),
                )

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for *key*, or None if missing/expired."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, fetched_at, ttl_seconds FROM cache WHERE key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None

        blob, fetched_at, ttl_seconds = row
        if time.time() - fetched_at > ttl_seconds:
            return None

        return pickle.loads(blob)  # noqa: S301 — trusted internal data

    def delete(self, key: str) -> None:
        """Remove a single key from the cache."""
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def purge_expired(self) -> int:
        """Delete all expired rows and return the count removed."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM cache WHERE (? - fetched_at) > ttl_seconds",
                    (now,),
                )
                return cursor.rowcount

    def exists(self, key: str) -> bool:
        """Return True if *key* exists in the cache AND has not expired."""
        return self.get(key) is not None

    def execute(self, sql: str, params: tuple = ()) -> list:
        """Execute arbitrary SQL and return all rows. For custom table queries."""
        with self._lock:
            cursor = self._conn.execute(sql, params)
            return cursor.fetchall()

    def execute_write(self, sql: str, params: tuple = ()) -> int:
        """Execute write SQL (INSERT/UPDATE/DELETE). Returns lastrowid."""
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor.lastrowid


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def get_db() -> CacheDB:
    """Return the process-wide CacheDB singleton (default vrp_cache.db)."""
    return CacheDB()
