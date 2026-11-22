"""Shared helpers for querying and validating against series_catalog."""
from __future__ import annotations
import sqlite3

FREQUENCY_EXPECTED_DAYS = {
    "hourly": 0.25, "daily": 1.0, "daily_forecast": 1.0,
    "weekly": 7.0, "monthly": 31.0, "quarterly_auction": 92.0, "annual": 366.0,
}

def has_catalog(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='series_catalog'").fetchone() is not None

def check_unit_consistency(conn: sqlite3.Connection, agent_id: str, unit: str) -> tuple[bool, str]:
    clean_unit = (unit or "").strip()
    if not clean_unit or not has_catalog(conn):
        return True, "ok"
    rows = conn.execute("SELECT DISTINCT unit FROM series_catalog WHERE agent_id=? AND is_active=1 AND unit IS NOT NULL AND unit<>''", (agent_id,)).fetchall()
    expected = {r[0] for r in rows}
    if expected and clean_unit not in expected:
        return False, f"unit {clean_unit!r} conflicts with cataloged {sorted(expected)} for {agent_id}"
    return True, "ok"

def list_series(conn: sqlite3.Connection, *, domain: str | None = None, active_only: bool = True) -> list[dict]:
    if not has_catalog(conn):
        return []
    clauses, args = (["is_active = 1"] if active_only else []), []
    if domain:
        clauses.append("domain = ?")
        args.append(domain)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur = conn.execute(f"SELECT catalog_id,agent_id,series_id,source_id,domain,frequency,unit,geographic_scope,first_target_timestamp,last_target_timestamp,observation_count,is_active FROM series_catalog {where} ORDER BY domain,agent_id,source_id", args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def active_agents(conn: sqlite3.Connection, domain: str | None = None) -> list[str]:
    if not has_catalog(conn):
        return [r[0] for r in conn.execute("SELECT DISTINCT agent_id FROM pit_market_data WHERE source_id IS NOT NULL AND source_id<>'' ORDER BY agent_id")]
    q = "SELECT DISTINCT agent_id FROM series_catalog WHERE is_active=1" + (" AND domain=?" if domain else "") + " ORDER BY agent_id"
    return [r[0] for r in conn.execute(q, (domain,) if domain else ())]

def agent_cadence_days(conn: sqlite3.Connection, agent_id: str) -> float | None:
    if not has_catalog(conn):
        return None
    rows = conn.execute("SELECT frequency FROM series_catalog WHERE agent_id=? AND is_active=1", (agent_id,)).fetchall()
    days = [FREQUENCY_EXPECTED_DAYS[r[0]] for r in rows if r[0] in FREQUENCY_EXPECTED_DAYS]
    return min(days) if days else None
