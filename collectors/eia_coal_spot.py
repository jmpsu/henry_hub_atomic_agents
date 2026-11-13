"""EIA weekly coal commodity spot prices (keyless JSON behind https://www.eia.gov/coal/markets/):
https://www.eia.gov/coal/markets/coal_markets_archive_json.php  block `snl_dpst` (USD per short ton, weekly since 2011).
  Agent_Coal_CAPP_SpotPrice  <- CENTRAL_APP         (Central Appalachia 12,500 Btu, 1.2 SO2)
  Agent_Coal_PRB_SpotPrice   <- POWDER_RIVER_BASIN  (Powder River Basin 8,800 Btu, 0.8 SO2)
The archive's `nymex` WESTERN_RAIL/EASTERN_RAIL columns are coal FUTURES, not rail freight rates, so they are not used
for Agent_Coal_Rail_TransportRate (which stays without a collector).
PIT assumption (documented, conservative): the week ending Friday D is published by the following Tuesday, 17:00Z (D+4).
A later changed value is stored as a new vintage available at retrieval time."""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

URL = "https://www.eia.gov/coal/markets/coal_markets_archive_json.php"
COLUMNS = {"CENTRAL_APP": ("Agent_Coal_CAPP_SpotPrice", "Central Appalachia (12,500 Btu, 1.2 SO2)"),
           "POWDER_RIVER_BASIN": ("Agent_Coal_PRB_SpotPrice", "Powder River Basin (8,800 Btu, 0.8 SO2)")}


def fetch(url):
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def parse(body: bytes) -> list:
    d = json.loads(body)
    blocks = [b["snl_dpst"] for b in d.get("data", []) if isinstance(b, dict) and "snl_dpst" in b]
    if len(blocks) != 1:
        raise ValueError("snl_dpst block not found (layout change?)")
    out = []
    for row in blocks[0]:
        wk = row.get("WEEK_ENDING_DATE")
        if not isinstance(wk, int) or not 20000101 < wk < 21000101:
            continue
        for col in COLUMNS:
            if col not in row:
                raise ValueError(f"column {col} missing (layout change?)")
            v = row[col]
            if isinstance(v, (int, float)) and v > 0:
                out.append((datetime.strptime(str(wk), "%Y%m%d").date(), col, float(v)))
    if not out:
        raise ValueError("no coal prices parsed")
    return out


def collect(conn, fetcher=fetch, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"EIA coal markets HTTP {status}")
    h = ingest.archive_payload(conn, body, "eia_coal_markets", URL, status, retrieved, ctype)
    rows = parse(body)
    known = {a: {r[1][:10]: r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [a], measured_only=False)} for a, _ in COLUMNS.values()}
    new = dict.fromkeys(known, 0)
    for wk, col, v in rows:
        agent, scope = COLUMNS[col]
        prev = known[agent].get(wk.isoformat())
        if prev is not None and abs(prev - v) < 1e-9:
            continue
        revised = prev is not None
        avail = retrieved if revised else (datetime(wk.year, wk.month, wk.day, tzinfo=timezone.utc) + timedelta(days=4, hours=17)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not revised and avail > retrieved:
            continue
        new[agent] += int(ingest.record_observation(
            conn, agent_id=agent, target_timestamp=wk.isoformat() + "T00:00:00Z", available_timestamp=avail, value=v, source_id="eia_coal_markets",
            source_url=URL, unit="USD/short ton", retrieved_timestamp=retrieved, revision_timestamp=retrieved if revised else None,
            geographic_scope=scope, series_id=f"snl_dpst.{col}", raw_payload_hash=h, extraction_version="eia_coal_spot/1",
            quality_status="revision_vintage" if revised else "validated_availability_assumed_tuesday", provenance="measured"))
    conn.commit()
    return [{"agent": a, "observations_new": n} for a, n in new.items()]


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(collect(sqlite3.connect(db)))
