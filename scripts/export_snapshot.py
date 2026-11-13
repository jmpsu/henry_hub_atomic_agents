#!/usr/bin/env python3
"""Section 3.5 GitHub data audit: write a deterministic, text-only snapshot of what the platform knew at a cutoff.

    snapshots/<YYYY-MM-DD>/manifest.json      per-agent coverage + a content digest of every PIT row available by the cutoff
    snapshots/<YYYY-MM-DD>/sources.json       raw payload manifest (hash, source, url, size, retrieved) - payloads stay in raw/
    snapshots/<YYYY-MM-DD>/ingestion.json     extraction versions, quality statuses, provenance counts, vintages per agent
    snapshots/<YYYY-MM-DD>/experiments.json   every recorded backtest experiment (incl. rejected)
    snapshots/<YYYY-MM-DD>/LEADERBOARD.md     copy of the leaderboard at export time

Deterministic: the same database and cutoff always produce byte-identical files (sorted keys, no wall-clock fields except
the cutoff itself), so `git diff` between two snapshots shows exactly what changed. Nothing secret is read: only
pit_market_data, raw_payloads (metadata, not bytes) and experiments. The multi-MB database itself is never committed.

Usage: scripts/export_snapshot.py [--as-of 2026-11-13T23:59:59Z] [--out snapshots] [--db henry_hub_pit.db]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "pit-snapshot/1"
ROW_COLS = ("agent_id", "target_timestamp", "available_timestamp", "value", "source_id", "unit", "series_id", "raw_payload_hash",
            "extraction_version", "quality_status", "provenance", "revision_timestamp")


def cutoff(as_of: str | None) -> str:
    if not as_of:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")
    dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def build(db_path: str, as_of: str) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        agents = {}
        total = hashlib.sha256()
        q = f"SELECT {','.join(ROW_COLS)} FROM pit_market_data WHERE available_timestamp<=? ORDER BY agent_id, target_timestamp, available_timestamp"
        cur_agent, h, rows = None, None, []

        def close():
            if cur_agent is None:
                return
            targets = [r[1] for r in rows]
            agents[cur_agent] = {"rows": len(rows), "targets": len(set(targets)), "first_target": min(targets), "last_target": max(targets),
                                 "last_available": max(r[2] for r in rows), "rows_sha256": h.hexdigest()}

        for r in conn.execute(q, (as_of,)):
            if r[0] != cur_agent:
                close()
                cur_agent, h, rows = r[0], hashlib.sha256(), []
            line = json.dumps([None if v is None else (round(v, 10) if isinstance(v, float) else v) for v in r], separators=(",", ":")) + "\n"
            h.update(line.encode())
            total.update(line.encode())
            rows.append(r)
        close()
        try:
            roster = sorted(a["agent_id"] for a in json.loads((ROOT / "agents_roster.json").read_text()))
        except Exception:  # noqa: BLE001
            roster = []
        real = {a for a, v in agents.items()}
        seeds = {r[0] for r in conn.execute("SELECT DISTINCT agent_id FROM pit_market_data WHERE available_timestamp<=? AND "
                                            "(COALESCE(quality_status,'')='unverified_seed' OR source_id IS NULL OR source_id='')", (as_of,))}
        seed_only = {a for a in seeds if not conn.execute(
            "SELECT 1 FROM pit_market_data WHERE agent_id=? AND available_timestamp<=? AND COALESCE(quality_status,'')<>'unverified_seed' "
            "AND source_id IS NOT NULL AND source_id<>'' LIMIT 1", (a, as_of)).fetchone()}
        manifest = {"schema": SCHEMA, "as_of": as_of, "database_rows_sha256": total.hexdigest(), "pit_rows": sum(v["rows"] for v in agents.values()),
                    "agents_with_rows": len(agents), "roster_agents": len(roster),
                    "roster_agents_with_real_data": sorted(a for a in roster if a in real and a not in seed_only),
                    "roster_agents_without_real_data": sorted(a for a in roster if a not in real or a in seed_only),
                    "agents": agents}
        sources = [dict(zip(("raw_payload_hash", "source_id", "source_url", "http_status", "retrieved_timestamp", "content_type", "byte_length"), r))
                   for r in conn.execute("SELECT raw_payload_hash,source_id,source_url,http_status,retrieved_timestamp,content_type,byte_length "
                                         "FROM raw_payloads WHERE retrieved_timestamp<=? ORDER BY retrieved_timestamp, raw_payload_hash", (as_of,))]
        ing = {}
        for a, ev, qs, pv, n in conn.execute(
                "SELECT agent_id, COALESCE(extraction_version,''), COALESCE(quality_status,''), COALESCE(provenance,'measured'), COUNT(*) FROM pit_market_data "
                "WHERE available_timestamp<=? GROUP BY 1,2,3,4 ORDER BY 1,2,3,4", (as_of,)):
            e = ing.setdefault(a, {"extraction_versions": {}, "quality_status": {}, "provenance": {}})
            for k, v in (("extraction_versions", ev), ("quality_status", qs), ("provenance", pv)):
                e[k][v] = e[k].get(v, 0) + n
        for a, mx in conn.execute("SELECT agent_id, MAX(c) FROM (SELECT agent_id, target_timestamp, COUNT(*) c FROM pit_market_data WHERE available_timestamp<=? "
                                  "GROUP BY 1,2) GROUP BY 1", (as_of,)):
            ing[a]["max_vintages_per_target"] = mx
        try:
            exps = [{"id": r[0], "created": r[1], "config": json.loads(r[2]), "pit_data_version": r[3], "train_period": r[4], "validation_period": r[5],
                     "test_period": r[6], "metrics": json.loads(r[7] or "{}"), "baseline_metrics": json.loads(r[8] or "{}"), "promoted": bool(r[9]), "result": r[10]}
                    for r in conn.execute("SELECT id,created,config,data_version,train_period,val_period,test_period,metrics,baseline_metrics,promoted,reason "
                                          "FROM experiments WHERE created<=? ORDER BY created, id", (as_of,))]
        except sqlite3.OperationalError:
            exps = []
        return {"manifest": manifest, "sources": {"schema": SCHEMA, "as_of": as_of, "payloads": sources,
                                                  "note": "Payload bytes are archived under raw/<sha256> on the host and are not committed."},
                "ingestion": {"schema": SCHEMA, "as_of": as_of, "agents": ing},
                "experiments": {"schema": SCHEMA, "as_of": as_of, "experiments": exps, "promoted": [e["id"] for e in exps if e["promoted"]]}}
    finally:
        conn.close()


def write(db_path: str, as_of: str, out_root: Path) -> Path:
    data = build(db_path, as_of)
    out = out_root / as_of[:10]
    out.mkdir(parents=True, exist_ok=True)
    for name, obj in data.items():
        (out / f"{name}.json").write_text(_dump(obj))
    lb = ROOT / "LEADERBOARD.md"
    if lb.exists():
        shutil.copyfile(lb, out / "LEADERBOARD.md")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db"))
    ap.add_argument("--as-of", default=None, help="cutoff (default: now, UTC)")
    ap.add_argument("--out", default=str(ROOT / "snapshots"))
    a = ap.parse_args(argv)
    out = write(a.db, cutoff(a.as_of), Path(a.out))
    m = json.loads((out / "manifest.json").read_text())
    print(json.dumps({"snapshot": str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out), "as_of": m["as_of"], "pit_rows": m["pit_rows"],
                      "agents_with_rows": m["agents_with_rows"], "roster_without_real_data": len(m["roster_agents_without_real_data"]),
                      "database_rows_sha256": m["database_rows_sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
