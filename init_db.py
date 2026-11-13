"""Create/migrate the PIT schema. Additive and idempotent: never drops or rewrites rows.
Usage: python init_db.py [path]   (defaults to $DB_PATH or ./henry_hub_pit.db)"""
import os
import sqlite3
import sys

PRODUCTION_COLUMNS = {
    "source_id": "TEXT",
    "source_url": "TEXT",
    "retrieved_timestamp": "TEXT",
    "published_timestamp": "TEXT",
    "revision_timestamp": "TEXT",
    "unit": "TEXT",
    "geographic_scope": "TEXT",
    "series_id": "TEXT",
    "raw_payload_hash": "TEXT",
    "extraction_version": "TEXT",
    "quality_status": "TEXT DEFAULT 'unvalidated'",
    "provenance": "TEXT",
}


def migrate(path: str) -> list:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pit_market_data (
            agent_id TEXT NOT NULL, target_timestamp TEXT NOT NULL,
            available_timestamp TEXT NOT NULL, value REAL NOT NULL,
            PRIMARY KEY (agent_id, target_timestamp, available_timestamp));
        CREATE INDEX IF NOT EXISTS idx_pit_backtest
            ON pit_market_data (available_timestamp, agent_id);
        CREATE TABLE IF NOT EXISTS raw_payloads (
            raw_payload_hash TEXT PRIMARY KEY, source_id TEXT, source_url TEXT,
            http_status INTEGER, retrieved_timestamp TEXT NOT NULL,
            content_type TEXT, byte_length INTEGER, archive_path TEXT NOT NULL);
        """
    )
    have = {r[1] for r in conn.execute("PRAGMA table_info(pit_market_data)")}
    added = []
    for col, decl in PRODUCTION_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE pit_market_data ADD COLUMN {col} {decl}")
            added.append(col)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pit_agent_target ON pit_market_data (agent_id, target_timestamp, available_timestamp)")
    conn.commit()
    conn.close()
    return added


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DB_PATH", "henry_hub_pit.db")
    print("migrated", target, "added columns:", migrate(target))
