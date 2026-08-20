"""
database.py
Person 2 — Backend Logic, Rules & LLM Integration

Small helper module that owns the SQLite connection and makes sure
schema.sql has been applied. Every service/router imports get_db()
from here instead of opening its own connection.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "stats_store.db"
SCHEMA_PATH = BASE_DIR / "data" / "schema.sql"


def init_db() -> None:
    """Create the database file and apply schema.sql if tables don't exist yet.
    Safe to call every time the app starts (CREATE TABLE IF NOT EXISTS)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()


def get_connection() -> sqlite3.Connection:
    """Raw connection with row access by column name (row['col'])."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """FastAPI dependency: `db: sqlite3.Connection = Depends(get_db)`.
    Commits on success, rolls back on error, always closes."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
