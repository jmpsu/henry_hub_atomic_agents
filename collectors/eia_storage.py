"""EIA Weekly Natural Gas Storage Report (keyless CSV) -> six regional storage agents.
PIT: available_timestamp is the report's stated release time (10:30 a.m. ET). Only the current week is recorded
as new; the prior-week column is recorded only when it differs from a vintage we already hold (a revision)."""
import csv
import io
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

URL = "https://ir.eia.gov/ngs/wngsr.csv"
REGIONS = {"East": "Agent_Storage_East", "Midwest": "Agent_Storage_Midwest", "Mountain": "Agent_Storage_Mountain",
           "Pacific": "Agent_Storage_Pacific", "Salt": "Agent_Storage_SouthCentral_Salt",
           "Nonsalt": "Agent_Storage_SouthCentral_NonSalt"}
ET = ZoneInfo("America/New_York")


def parse(text: str) -> dict:
    text = text.lstrip("﻿")
    m = re.search(r'Released:\s*([A-Za-z]+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2}) ([ap])\.m\.', text)
    w = re.search(r'Week Ending ([A-Za-z]+ \d{1,2}, \d{4})', text)
    if not m or not w:
        raise ValueError("unexpected EIA layout: release/week header missing")
    rel = datetime.strptime(f"{m[1]} {m[2]} {m[3].upper()}M", "%B %d, %Y %I:%M %p").replace(tzinfo=ET)
    week_end = datetime.strptime(w[1], "%B %d, %Y")
    rows = list(csv.reader(io.StringIO(text)))
    hdr = next((r for r in rows if len(r) > 4 and re.fullmatch(r"\d{1,2}-[A-Za-z]{3}-\d{2}", r[1].strip())), None)
    if not hdr:
        raise ValueError("unexpected EIA layout: date header row missing")
    cur_date = datetime.strptime(hdr[1].strip(), "%d-%b-%y")
    prior_date = datetime.strptime(hdr[4].strip(), "%d-%b-%y")
    if cur_date.date() != week_end.date():
        raise ValueError("week-ending mismatch between title and column header")
    values = {}
    for r in rows:
        key = r[0].strip() if r else ""
        if key in REGIONS and len(r) > 4:
            values[key] = (float(r[1].replace(",", "")), float(r[4].replace(",", "")))
    if set(values) != set(REGIONS):
        raise ValueError(f"missing regions: {set(REGIONS) - set(values)}")
    return {"released": rel.astimezone(timezone.utc), "current": cur_date, "prior": prior_date, "values": values}


def fetch(url):
    r = httpx.get(url, timeout=30, follow_redirects=True)
    return r.status_code, r.content, r.headers.get("content-type", "")


def collect(conn, fetcher=fetch, now: datetime = None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"EIA storage: HTTP {status}")
    h = ingest.archive_payload(conn, body, "eia_wngsr", URL, status, retrieved, ctype)
    p = parse(body.decode("utf-8-sig"))
    avail = p["released"].strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for region, agent in REGIONS.items():
        cur, prior = p["values"][region]
        new = 0
        for date, val, is_prior in ((p["current"], cur, False), (p["prior"], prior, True)):
            day = date.strftime("%Y-%m-%dT00:00:00Z")
            known = {r[1]: r[3] for r in ingest.pit_snapshot(conn, retrieved, [agent])}
            if known.get(day) == val:
                continue
            if is_prior and day not in known:
                continue  # never fabricate an earlier availability for a value we did not see published
            new += int(ingest.record_observation(
                conn, agent_id=agent, target_timestamp=day, available_timestamp=avail, value=val,
                source_id="eia_wngsr", source_url=URL, unit="Bcf", retrieved_timestamp=retrieved,
                published_timestamp=avail, geographic_scope=f"Lower 48 - {region}", series_id=f"EIA_WNGSR_{region.upper()}",
                raw_payload_hash=h, extraction_version="eia_storage/1", quality_status="validated", provenance="measured"))
        out.append({"agent": agent, "observations_new": new})
    conn.commit()
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    for r in collect(sqlite3.connect(db)):
        print(r)
