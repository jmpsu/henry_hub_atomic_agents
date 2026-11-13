"""One-off backfill: NOAA CPC CONUS population-weighted observed HDD/CDD 1981..today, plus the derived
Agent_Weather_30YrNormal_HDD (mean HDD per calendar day over 1991-2020, the NOAA normals period).
PIT assumptions (documented): an observed day D is treated as available D+1 12:00Z (CPC posts the next morning; historic
revision timing is unknowable); the 1991-2020 normal is available from 2021-05-04 (NOAA normals release) for every target date."""
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
from collectors import cpc_degree_days as cpc  # noqa: E402

NORMAL_FROM, NORMAL_TO = 1991, 2020
NORMAL_AVAILABLE = "2021-05-04T00:00:00Z"


def avail_for(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=1, hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")


def normals(hdd_by_day: dict) -> dict:
    """{'MM-DD': mean HDD over 1991-2020}. Requires >=25 of 30 years present for a calendar day."""
    acc = defaultdict(list)
    for day, v in hdd_by_day.items():
        if NORMAL_FROM <= int(day[:4]) <= NORMAL_TO:
            acc[day[5:]].append(v)
    return {md: sum(v) / len(v) for md, v in acc.items() if len(v) >= 25}


def backfill(conn, fetcher=cpc.fetch, now=None, first_year=1981) -> dict:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    stats, hdd_all = {}, {}
    for kind, agent in cpc.AGENTS.items():
        new = 0
        for year in range(first_year, now.year + 1):   # current year too, under the same D+1 rule (days not yet 'public' are skipped)
            url = cpc.BASE.format(year=year, kind=kind)
            status, body, ctype = fetcher(url)
            if status != 200:
                continue
            h = ingest.archive_payload(conn, body, "noaa_cpc_degree_days_history", url, status, retrieved, ctype)
            for day, v in cpc.parse(body.decode()).items():
                if avail_for(day) > retrieved:
                    continue
                if kind == "Heating":
                    hdd_all[day] = v
                new += int(ingest.record_observation(
                    conn, agent_id=agent, target_timestamp=day + "T00:00:00Z", available_timestamp=avail_for(day), value=v,
                    source_id="noaa_cpc_degree_days_history", source_url=url, unit="population-weighted degree days",
                    retrieved_timestamp=retrieved, geographic_scope="CONUS", series_id=f"CPC_{kind.upper()}_CONUS",
                    raw_payload_hash=h, extraction_version="cpc_history/1", quality_status="validated_availability_assumed_d+1",
                    provenance="measured"))
            conn.commit()
        stats[agent] = new
    norm = normals(hdd_all)
    n_new = 0
    start = datetime(NORMAL_FROM, 1, 1)
    for i in range((datetime(now.year + 1, 12, 31) - start).days + 1):
        d = start + timedelta(days=i)
        v = norm.get(d.strftime("%m-%d"))
        if v is None:
            continue
        n_new += int(ingest.record_observation(
            conn, agent_id="Agent_Weather_30YrNormal_HDD", target_timestamp=d.strftime("%Y-%m-%dT00:00:00Z"),
            available_timestamp=NORMAL_AVAILABLE, value=round(v, 3), source_id="derived_from_noaa_cpc_degree_days_history",
            source_url="derived", unit="population-weighted degree days", retrieved_timestamp=retrieved, geographic_scope="CONUS",
            series_id="CPC_HDD_NORMAL_1991_2020", extraction_version="cpc_history/1", quality_status="derived_validated",
            provenance="extracted_estimate"))
    conn.commit()
    stats["Agent_Weather_30YrNormal_HDD"] = n_new
    return stats


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(backfill(sqlite3.connect(db)))
