"""NOAA CPC population-weighted CONUS degree days -> Agent_Weather_Actual_HDD / _CDD.
PIT rule: the source file is overwritten daily and its history is unknowable, so every observation is
available at OUR retrieval time (conservative, no look-ahead). A changed value on a later run is a new vintage."""
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

BASE = "https://ftp.cpc.ncep.noaa.gov/htdocs/degree_days/weighted/daily_data/{year}/Population.{kind}.txt"
AGENTS = {"Heating": "Agent_Weather_Actual_HDD", "Cooling": "Agent_Weather_Actual_CDD"}


def parse(text: str) -> dict:
    """Return {YYYY-MM-DD: value} for the CONUS row. Rejects any file whose layout is not as expected."""
    lines = [l for l in text.splitlines() if l.strip()]
    header = next((l for l in lines if l.startswith("Region|")), None)
    conus = next((l for l in lines if l.startswith("CONUS|")), None)
    if not header or not conus:
        raise ValueError("unexpected CPC layout: header or CONUS row missing")
    dates = header.split("|")[1:]
    vals = conus.split("|")[1:]
    out = {}
    for d, v in zip(dates, vals):
        if not (d.isdigit() and len(d) == 8) or not v.strip().lstrip("-").isdigit():
            continue
        out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = float(v)
    if not out:
        raise ValueError("no parsable observations")
    return out


def fetch(url: str) -> tuple:
    r = httpx.get(url, timeout=30, follow_redirects=True)
    return r.status_code, r.content, r.headers.get("content-type", "")


def collect(conn, kind: str, year: int, fetcher=fetch, now: datetime = None) -> dict:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = BASE.format(year=year, kind=kind)
    status, body, ctype = fetcher(url)
    agent = AGENTS[kind]
    if status != 200:
        raise RuntimeError(f"{agent}: HTTP {status} from {url}")
    h = ingest.archive_payload(conn, body, "noaa_cpc_degree_days", url, status, retrieved, ctype)
    new = 0
    for day, value in parse(body.decode()).items():
        snap = ingest.pit_snapshot(conn, retrieved, [agent])
        known = {r[1][:10]: r[3] for r in snap}
        if known.get(day) == value:
            continue  # same vintage already recorded
        ok = ingest.record_observation(
            conn, agent_id=agent, target_timestamp=day + "T00:00:00Z", available_timestamp=retrieved, value=value,
            source_id="noaa_cpc_degree_days", source_url=url, unit="population-weighted degree days",
            retrieved_timestamp=retrieved, geographic_scope="CONUS", series_id=f"CPC_{kind.upper()}_CONUS",
            raw_payload_hash=h, extraction_version="cpc_degree_days/1", quality_status="validated", provenance="measured")
        new += int(ok)
    conn.commit()
    return {"agent": agent, "observations_new": new, "raw_payload_hash": h}


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    conn = sqlite3.connect(db)
    year = datetime.now(timezone.utc).year
    for kind in AGENTS:
        print(collect(conn, kind, year))
