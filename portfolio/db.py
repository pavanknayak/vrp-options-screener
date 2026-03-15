"""SQLite persistence for open positions in the Portfolio Monitor.

Reuses the same SQLite database as the cache layer (vrp_cache.db in project root).
Creates a 'portfolio_positions' table if it does not exist.
"""
import sqlite3
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# Reuse the same DB as the cache layer
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "vrp_cache.db")


@dataclass
class Position:
    id: Optional[int]                    # None for new positions (DB assigns)
    ticker: str
    structure: str                       # 'csp', 'spread', 'collar', 'covered_call', etc.
    expiry: str                          # ISO date string e.g. '2026-05-16'
    short_strike: float
    long_strike: Optional[float]         # None for CSP/covered call (single-leg)
    net_credit: float                    # per-share credit received
    quantity: int                        # number of contracts
    is_short_vol: bool = True            # True for premium-selling structures
    notes: str = ""
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    entry_price: float = 0.0             # underlying price at entry
    sector: str = "Unknown"             # sector for concentration tracking
    paper: bool = False                 # True for paper trading positions


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT NOT NULL,
            structure    TEXT NOT NULL,
            expiry       TEXT NOT NULL,
            short_strike REAL NOT NULL,
            long_strike  REAL,
            net_credit   REAL NOT NULL DEFAULT 0.0,
            quantity     INTEGER NOT NULL DEFAULT 1,
            is_short_vol INTEGER NOT NULL DEFAULT 1,
            notes        TEXT DEFAULT '',
            created_at   TEXT NOT NULL
        )
    """)
    conn.commit()


def save_position(pos: Position) -> int:
    """Insert a new position. Returns the new row id."""
    with _get_conn() as conn:
        _ensure_table(conn)
        cur = conn.execute(
            """INSERT INTO portfolio_positions
               (ticker, structure, expiry, short_strike, long_strike,
                net_credit, quantity, is_short_vol, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pos.ticker, pos.structure, pos.expiry, pos.short_strike,
             pos.long_strike, pos.net_credit, pos.quantity,
             int(pos.is_short_vol), pos.notes, pos.created_at),
        )
        conn.commit()
        return cur.lastrowid


def load_positions() -> list[Position]:
    """Load all positions from the database."""
    with _get_conn() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM portfolio_positions ORDER BY created_at DESC"
        ).fetchall()
    return [
        Position(
            id=row["id"],
            ticker=row["ticker"],
            structure=row["structure"],
            expiry=row["expiry"],
            short_strike=row["short_strike"],
            long_strike=row["long_strike"],
            net_credit=row["net_credit"],
            quantity=row["quantity"],
            is_short_vol=bool(row["is_short_vol"]),
            notes=row["notes"] or "",
            created_at=row["created_at"],
        )
        for row in rows
    ]


def delete_position(position_id: int) -> None:
    """Delete a position by id."""
    with _get_conn() as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM portfolio_positions WHERE id = ?", (position_id,))
        conn.commit()


def save_paper_position(pos: Position) -> int:
    """Save a paper trading position to paper_positions table. Returns the new row id."""
    import time
    from cache.db import get_db
    db = get_db()
    return db.execute_write(
        """INSERT INTO paper_positions
           (ticker, structure, short_strike, long_strike, expiration_date,
            contracts, entry_credit, entry_price, entry_date, sector, notes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pos.ticker,
            pos.structure,
            pos.short_strike,
            pos.long_strike,
            pos.expiry,
            pos.quantity,
            pos.net_credit,
            pos.entry_price,
            pos.created_at,
            pos.sector,
            pos.notes,
            time.time(),
        ),
    )


def load_paper_positions() -> list[dict]:
    """Load all paper trading positions from paper_positions table."""
    from cache.db import get_db
    db = get_db()
    rows = db.execute(
        """SELECT id, ticker, structure, short_strike, long_strike,
                  expiration_date, contracts, entry_credit, entry_price,
                  entry_date, sector, notes, created_at
           FROM paper_positions
           ORDER BY created_at DESC"""
    )
    return [
        {
            "id": row[0],
            "ticker": row[1],
            "structure": row[2],
            "short_strike": row[3],
            "long_strike": row[4],
            "expiration_date": row[5],
            "contracts": row[6],
            "entry_credit": row[7],
            "entry_price": row[8],
            "entry_date": row[9],
            "sector": row[10] or "Unknown",
            "notes": row[11] or "",
            "created_at": row[12],
        }
        for row in rows
    ]


def delete_paper_position(position_id: int) -> None:
    """Delete a paper trading position by ID."""
    from cache.db import get_db
    db = get_db()
    db.execute_write(
        "DELETE FROM paper_positions WHERE id = ?",
        (position_id,),
    )
