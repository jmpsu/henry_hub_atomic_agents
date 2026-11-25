"""Shared helpers for querying and validating against series_catalog."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone

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


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _inferred_frequency(agent_id: str) -> str:
    if agent_id.startswith(("Agent_GFS_", "Agent_ECMWF_")):
        return "daily_forecast"
    if agent_id.startswith("Agent_Storage_"):
        return "weekly"
    if agent_id.startswith(("Agent_Prod_", "Agent_LNGExports_", "Agent_BorderFlow_")) or agent_id in {
        "Agent_Demand_Industrial", "Agent_Demand_ResComm", "Agent_TTF_EURUSD", "Agent_FX_EURUSD"}:
        return "monthly"
    return "daily"


def _observed_feed_status(conn: sqlite3.Connection, agent_id: str, as_of: str | None, base: dict,
                          frequency: str | None = None, source_ids: list[str] | None = None) -> dict | None:
    row = conn.execute(
        "SELECT MAX(available_timestamp), MAX(target_timestamp), GROUP_CONCAT(DISTINCT source_id) "
        "FROM pit_market_data WHERE agent_id=? AND available_timestamp<=?", (agent_id, as_of or "9999")).fetchone()
    if not row or not row[0]:
        return None
    frequency = frequency or _inferred_frequency(agent_id)
    cadence_days = FREQUENCY_EXPECTED_DAYS.get(frequency)
    end = _parse_timestamp(as_of) or datetime.now(timezone.utc)
    last_dt = _parse_timestamp(row[0])
    age_days = (end - last_dt).total_seconds() / 86400.0 if last_dt else None
    status, label = "ACTIVE", "Feed Active"
    if age_days is None or (cadence_days is not None and age_days > max(cadence_days * 3.0, cadence_days + 1.0)):
        status, label = "STALE", "Feed Not Fresh"
    ids = set(source_ids or [])
    ids.update(x for x in (row[2] or "").split(",") if x)
    return {**base, "status": status, "label": label, "source_ids": sorted(ids), "frequency": frequency,
            "cadence_days": cadence_days, "last_target_timestamp": row[1], "age_days": age_days, "observed": True}


def feed_status(conn: sqlite3.Connection, agent_id: str, as_of: str | None = None) -> dict:
    base = {"agent_id": agent_id, "status": "UNREGISTERED", "label": "Feed Not Configured",
            "source_ids": [], "frequency": None, "cadence_days": None, "last_target_timestamp": None,
            "age_days": None, "observed": False}
    rows = []
    if has_catalog(conn):
        rows = conn.execute(
            "SELECT is_active, source_id, frequency, last_target_timestamp, observation_count "
            "FROM series_catalog WHERE agent_id=? ORDER BY is_active DESC, catalog_id", (agent_id,)).fetchall()
    active = [r for r in rows if r[0] == 1]
    if rows and not active:
        return {**base, "status": "INACTIVE_OR_PLANNED_GAP", "source_ids": sorted({r[1] for r in rows})}
    if not active:
        return _observed_feed_status(conn, agent_id, as_of, base) or base
    cadence_days = min((FREQUENCY_EXPECTED_DAYS[r[2]] for r in active if r[2] in FREQUENCY_EXPECTED_DAYS), default=None)
    frequency = sorted({r[2] for r in active})[0]
    observed = _observed_feed_status(conn, agent_id, as_of, base, frequency, [r[1] for r in active])
    if observed:
        return observed
    last = max((r[3] for r in active if r[3]), default=None)
    end = _parse_timestamp(as_of) or datetime.now(timezone.utc)
    last_dt = _parse_timestamp(last)
    age_days = (end - last_dt).total_seconds() / 86400.0 if last_dt else None
    status, label = ("ACTIVE", "Feed Active") if age_days is not None and (
        cadence_days is None or age_days <= max(cadence_days * 3.0, cadence_days + 1.0)) else ("STALE", "Feed Not Fresh")
    return {**base, "status": status, "label": label, "source_ids": sorted({r[1] for r in active}),
            "frequency": frequency, "cadence_days": cadence_days, "last_target_timestamp": last,
            "age_days": age_days, "observed": True}
