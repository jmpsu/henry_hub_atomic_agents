"""Vintage-preserving ingestion core. Observations are only ever INSERTed; a revision is a new row
with a later available_timestamp, so history is never overwritten. Raw payloads are archived by hash."""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW_DIR = Path(os.environ.get("RAW_DIR", BASE / "raw"))


def utc_iso(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware: " + ts)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_dir() -> Path:
    """Archive directory, read per call (RAW_DIR env overrides) so tests and worktrees can redirect it."""
    return Path(os.environ.get("RAW_DIR", RAW_DIR))


def archive_payload(conn, payload: bytes, source_id: str, source_url: str, http_status: int,
                    retrieved: str, content_type: str = "") -> str:
    """Store the original bytes under raw/<sha256> (never overwritten) and index them."""
    h = hashlib.sha256(payload).hexdigest()
    d = raw_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / h
    if not path.exists():
        path.write_bytes(payload)
    conn.execute(
        "INSERT OR IGNORE INTO raw_payloads (raw_payload_hash,source_id,source_url,http_status,"
        "retrieved_timestamp,content_type,byte_length,archive_path) VALUES (?,?,?,?,?,?,?,?)",
        (h, source_id, source_url, http_status, utc_iso(retrieved), content_type, len(payload), str(path)))
    return h


def record_observation(conn, *, agent_id, target_timestamp, available_timestamp, value, source_id,
                       source_url="", unit="", retrieved_timestamp=None, published_timestamp=None,
                       revision_timestamp=None, geographic_scope="", series_id="", raw_payload_hash="",
                       extraction_version="", quality_status="unvalidated", provenance="measured") -> bool:
    """Insert one vintage. Returns False if this exact vintage already exists (idempotent re-runs).
    provenance is one of: measured, extracted_estimate, synthetic_scenario, model_hypothesis."""
    if provenance not in ("measured", "extracted_estimate", "synthetic_scenario", "model_hypothesis"):
        raise ValueError("bad provenance")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value != value:
        raise ValueError("value must be a finite number")
    from ingestion.validation.gatekeeper import check  # deterministic physical-range gate
    ok, reason = check(agent_id, float(value), unit)
    if not ok:
        raise ValueError(f"gatekeeper rejected {agent_id}: {reason}")
    cur = conn.execute(
        "INSERT OR IGNORE INTO pit_market_data (agent_id,target_timestamp,available_timestamp,value,"
        "source_id,source_url,retrieved_timestamp,published_timestamp,revision_timestamp,unit,"
        "geographic_scope,series_id,raw_payload_hash,extraction_version,quality_status,provenance) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (agent_id, utc_iso(target_timestamp), utc_iso(available_timestamp), float(value), source_id,
         source_url, utc_iso(retrieved_timestamp) if retrieved_timestamp else None,
         utc_iso(published_timestamp) if published_timestamp else None,
         utc_iso(revision_timestamp) if revision_timestamp else None, unit, geographic_scope,
         series_id, raw_payload_hash, extraction_version, quality_status, provenance))
    return cur.rowcount == 1


def pit_snapshot(conn, as_of: str, agent_ids=None, measured_only=True) -> list:
    """What the platform knew at as_of: for each (agent_id, target_timestamp) the LATEST vintage with
    available_timestamp <= as_of. Later revisions are invisible."""
    as_of = utc_iso(as_of)
    q = ("SELECT p.agent_id,p.target_timestamp,p.available_timestamp,p.value FROM pit_market_data p "
         "WHERE p.available_timestamp <= ? "
         "AND p.available_timestamp = (SELECT MAX(q.available_timestamp) FROM pit_market_data q "
         "WHERE q.agent_id=p.agent_id AND q.target_timestamp=p.target_timestamp AND q.available_timestamp <= ?)")
    args = [as_of, as_of]
    if measured_only:
        q += " AND COALESCE(p.provenance,'measured')='measured'"
    if agent_ids:
        q += " AND p.agent_id IN (%s)" % ",".join("?" * len(agent_ids))
        args += list(agent_ids)
    return conn.execute(q + " ORDER BY p.agent_id,p.target_timestamp", args).fetchall()
