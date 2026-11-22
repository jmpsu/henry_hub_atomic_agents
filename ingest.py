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
    """Store the original bytes under raw/<sha256> (never overwritten) and index them. Payloads over 5 MB are stored
    gzip-compressed as raw/<sha256>.gz; the hash is always of the ORIGINAL bytes (read_payload() returns them)."""
    h = hashlib.sha256(payload).hexdigest()
    d = raw_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / h
    if len(payload) > 5_000_000:
        import gzip
        path = d / f"{h}.gz"
        if not path.exists():
            tmp = d / f".{h}.gz.part"
            tmp.write_bytes(gzip.compress(payload, compresslevel=6, mtime=0))
            tmp.replace(path)
    elif not path.exists():
        path.write_bytes(payload)
    conn.execute(
        "INSERT OR IGNORE INTO raw_payloads (raw_payload_hash,source_id,source_url,http_status,"
        "retrieved_timestamp,content_type,byte_length,archive_path) VALUES (?,?,?,?,?,?,?,?)",
        (h, source_id, source_url, http_status, utc_iso(retrieved), content_type, len(payload), str(path)))
    return h


def read_payload(archive_path: str) -> bytes:
    """Original payload bytes from an archive path (transparently decompresses .gz archives)."""
    p = Path(archive_path)
    if p.suffix == ".gz":
        import gzip
        return gzip.decompress(p.read_bytes())
    return p.read_bytes()


def record_observation(conn, *, agent_id, target_timestamp, available_timestamp, value, source_id,
                       source_url="", unit="", retrieved_timestamp=None, published_timestamp=None,
                       revision_timestamp=None, geographic_scope="", series_id="", raw_payload_hash="",
                       extraction_version="", quality_status="unvalidated", provenance="measured") -> bool:
    """Insert one vintage. Returns False if this exact vintage already exists (idempotent re-runs).
    provenance is one of: measured, extracted_estimate, synthetic_scenario, model_hypothesis, bootstrapped_physical_proxy
    (the last is the tag the LNG feedgas model must carry, checklist A4; like every non-'measured' class it is excluded from the measured-only readers)."""
    if provenance not in ("measured", "extracted_estimate", "synthetic_scenario", "model_hypothesis", "bootstrapped_physical_proxy"):
        raise ValueError("bad provenance")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value != value:
        raise ValueError("value must be a finite number")
    from ingestion.validation.gatekeeper import check  # deterministic physical-range gate
    ok, reason = check(agent_id, float(value), unit)
    if not ok:
        raise ValueError(f"gatekeeper rejected {agent_id}: {reason}")
    from series_catalog import check_unit_consistency
    u_ok, u_why = check_unit_consistency(conn, agent_id, unit)
    if not u_ok:
        raise ValueError(f"catalog rejected {agent_id}: {u_why}")
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
