#!/usr/bin/env python3
"""Idempotent, checksum-verified SQLite migration runner."""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent


def list_migrations() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_PATH", ""))
    ap.add_argument("--check", action="store_true", help="Verify all migrations are applied without modifying DB")
    args = ap.parse_args()

    if not args.db or not Path(args.db).is_file():
        print(f"ERROR: valid SQLite DB_PATH required, got: {args.db!r}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        files = list_migrations()
        if args.check:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "schema_migrations" not in tables:
                print("ERROR: schema_migrations table missing", file=sys.stderr)
                return 1
            applied = {
                r[0]: r[1]
                for r in conn.execute("SELECT version, checksum FROM schema_migrations")
            }
            for f in files:
                ver = f.name.split("_", 1)[0]
                csum = hashlib.sha256(f.read_bytes()).hexdigest()
                if applied.get(ver) != csum:
                    print(f"ERROR: migration {f.name} not applied or checksum mismatch", file=sys.stderr)
                    return 1
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                print(f"ERROR: PRAGMA integrity_check returned {integrity}", file=sys.stderr)
                return 1
            print(f"Migrations OK ({len(files)} verified, integrity=ok)")
            return 0

        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
        )
        conn.commit()
        applied = {
            r[0]: r[1]
            for r in conn.execute("SELECT version, checksum FROM schema_migrations")
        }

        for f in files:
            ver = f.name.split("_", 1)[0]
            sql = f.read_text(encoding="utf-8")
            csum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if ver in applied:
                if applied[ver] != csum:
                    print(f"ERROR: checksum drift for applied migration {f.name}", file=sys.stderr)
                    return 1
                continue
            with conn:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                    (ver, f.name, datetime.now(timezone.utc).isoformat(), csum),
                )
            print(f"Applied migration: {f.name}")

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            print(f"ERROR: PRAGMA integrity_check failed: {integrity}", file=sys.stderr)
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
