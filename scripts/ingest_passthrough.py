#!/usr/bin/env python3
"""Archive and ingest external JSON/CSV observations into raw_payloads and pit_market_data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def ingest_records(
    records: list[dict],
    raw_bytes: bytes,
    source_id: str,
    source_url: str,
    provenance: str,
    quality_status: str,
    db_path: str | None = None,
) -> int:
    db = db_path or os.environ["DB_PATH"]
    root_dir = Path(__file__).resolve().parent.parent
    raw_dir = root_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(raw_bytes).hexdigest()
    (raw_dir / sha).write_bytes(raw_bytes)
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = sqlite3.connect(db, timeout=30.0)
    inserted = 0
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO raw_payloads "
                "(raw_payload_hash, source_id, source_url, http_status, retrieved_timestamp, content_type, byte_length, archive_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sha, source_id, source_url, 200, now_ts, "application/json", len(raw_bytes), f"raw/{sha}"),
            )
            for rec in records:
                agent_id = rec["agent_id"]
                target_ts = rec["target_timestamp"]
                avail_ts = rec.get("available_timestamp") or now_ts
                exists = conn.execute(
                    "SELECT 1 FROM pit_market_data WHERE agent_id=? AND target_timestamp=? AND available_timestamp=?",
                    (agent_id, target_ts, avail_ts),
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    "INSERT INTO pit_market_data ("
                    "agent_id, target_timestamp, available_timestamp, value, "
                    "source_id, source_url, retrieved_timestamp, published_timestamp, revision_timestamp, "
                    "unit, geographic_scope, series_id, raw_payload_hash, extraction_version, quality_status, provenance"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        agent_id, target_ts, avail_ts, float(rec["value"]),
                        source_id, source_url, now_ts, rec.get("published_timestamp") or avail_ts, "",
                        rec.get("unit", ""), rec.get("geographic_scope", ""), rec.get("series_id", agent_id),
                        sha, "passthrough_v1", quality_status, provenance,
                    ),
                )
                inserted += 1
        return inserted
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to JSON array or CSV file")
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--source-url", default="passthrough://local")
    ap.add_argument("--provenance", default="measured", choices=["measured", "extracted_estimate"])
    ap.add_argument("--quality-status", default="validated")
    args = ap.parse_args()

    p = Path(args.input)
    raw_bytes = p.read_bytes()
    if p.suffix.lower() == ".csv":
        records = list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
    else:
        records = json.loads(raw_bytes.decode("utf-8"))
    n = ingest_records(records, raw_bytes, args.source_id, args.source_url, args.provenance, args.quality_status)
    print(f"Ingested {n} new observations (sha256={hashlib.sha256(raw_bytes).hexdigest()[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
