"""SQLite schema and connection helpers.

Run `python -m src.db init` to create / migrate the schema.

Two tables:
- ``daily_snapshot``: audit log, one row per (date, section, market_id).
- ``market_jp_label``: cached LLM translations keyed by slug (lower-case ticker).
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

SCHEMA = """
-- Daily snapshot: one row per (date, section, market) for audit + future trend analysis.
CREATE TABLE IF NOT EXISTS daily_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,         -- YYYY-MM-DD in JST
    market_id TEXT NOT NULL,
    slug TEXT,
    question TEXT,
    category TEXT,                       -- sector label (L1 majors / DeFi / Memes / …)
    yes_price REAL,                      -- coin mark price (USD); NULL for sector aggregates
    one_day_change REAL,                 -- fractional 24h change
    volume_24h_usd REAL,                 -- 24h notional volume USD
    section TEXT,                        -- 'buys' | 'sells' | 'sectors'
    rank_in_section INTEGER,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, section, market_id)
);

CREATE INDEX IF NOT EXISTS idx_daily_snapshot_date ON daily_snapshot(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_daily_snapshot_market ON daily_snapshot(market_id, snapshot_date);

-- Japanese label cache for coin slugs. Keyed by lower-case ticker (stable).
-- ``source`` distinguishes 'llm' (auto-translated) from 'manual' (operator-curated
-- via settings.yaml display_aliases) so manual entries always win the merge.
CREATE TABLE IF NOT EXISTS market_jp_label (
    slug TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'llm',
    question TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_schema(db_path: Path | str) -> None:
    conn = connect(db_path)
    try:
        with transaction(conn):
            conn.executescript(SCHEMA)
        log.info("Initialized schema at %s", db_path)
    finally:
        conn.close()


def _cli() -> None:
    from .config import load_settings

    parser = argparse.ArgumentParser(prog="src.db")
    parser.add_argument("command", choices=["init"], help="schema command")
    args = parser.parse_args()

    settings = load_settings()
    logging.basicConfig(level=settings.log_level)

    if args.command == "init":
        init_schema(settings.db_path)
        print(f"Initialized: {settings.db_path}")


if __name__ == "__main__":
    _cli()
