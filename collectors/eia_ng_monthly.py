"""EIA Natural Gas Monthly demand from the keyless bulk file https://www.eia.gov/opendata/bulk/NG.zip (NG.txt, JSON lines).
Agents: Agent_Demand_Industrial (N3035US2), Agent_Demand_ResComm (N3010US2 + N3020US2). Unit: Bcf/d = MMcf / 1000 / days_in_month.
Roster says 'Daily'; the source is MONTHLY national data converted to a monthly-average daily rate (documented limitation).
PIT: month M is treated as published at the end of month M+2 16:00Z (EIA NGM cadence, conservative vs actual ~end of M+2).
The bulk file carries only the LATEST vintage, so first-load history uses that rule and cannot reproduce past revisions
(quality_status says so). On later runs a changed value is stored as a NEW vintage available at retrieval time."""
import calendar
import io
import json
import os
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

URL = "https://www.eia.gov/opendata/bulk/NG.zip"
AGENTS = {"Agent_Demand_Industrial": ["NG.N3035US2.M"], "Agent_Demand_ResComm": ["NG.N3010US2.M", "NG.N3020US2.M"]}
FIRST = "200101"  # N3035 begins 2001-01


def fetch(url):
    r = httpx.get(url, timeout=180, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def parse(body: bytes) -> dict:
    """{series_id: {'YYYYMM': MMcf}} for the needed series; raises if a series is missing or malformed."""
    need = {s for v in AGENTS.values() for s in v}
    out = {}
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        for line in z.read("NG.txt").decode().splitlines():
            if not line.startswith('{"series_id"'):
                continue
            d = json.loads(line)
            if d["series_id"] in need:
                if d.get("units") != "Million Cubic Feet" or d.get("f") != "M":
                    raise ValueError(f"unexpected units/frequency for {d['series_id']}")
                out[d["series_id"]] = {p: v for p, v in d["data"] if v is not None}
    missing = need - set(out)
    if missing:
        raise ValueError(f"series missing from bulk file: {sorted(missing)}")
    return out


def release_ts(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[4:])
    m += 2
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}T16:00:00Z"


def bcfd(ym: str, mmcf: float) -> float:
    return mmcf / 1000.0 / calendar.monthrange(int(ym[:4]), int(ym[4:]))[1]


def collect(conn, fetcher=fetch, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"NG.zip HTTP {status}")
    h = ingest.archive_payload(conn, body, "eia_ng_bulk", URL, status, retrieved, ctype)
    data = parse(body)
    out = []
    for agent, sids in AGENTS.items():
        months = set.intersection(*[set(data[s]) for s in sids])
        known = {r[1][:7].replace("-", ""): r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [agent], measured_only=False)}
        new = 0
        for ym in sorted(m for m in months if m >= FIRST):
            val = round(bcfd(ym, sum(data[s][ym] for s in sids)), 4)
            prev = known.get(ym)
            if prev is not None and abs(prev - val) < 1e-9:
                continue
            revised = prev is not None
            new += int(ingest.record_observation(
                conn, agent_id=agent, target_timestamp=f"{ym[:4]}-{ym[4:]}-01T00:00:00Z",
                available_timestamp=retrieved if revised else release_ts(ym), value=val, source_id="eia_ng_bulk", source_url=URL,
                unit="Bcf/d (monthly average)", retrieved_timestamp=retrieved, revision_timestamp=retrieved if revised else None,
                geographic_scope="USA", series_id="+".join(s.split(".")[1] for s in sids), raw_payload_hash=h,
                extraction_version="eia_ng_monthly/1",
                quality_status="revision_vintage" if revised else "latest_vintage_release_rule_assumed", provenance="measured"))
        conn.commit()
        out.append({"agent": agent, "observations_new": new})
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(collect(sqlite3.connect(db)))
