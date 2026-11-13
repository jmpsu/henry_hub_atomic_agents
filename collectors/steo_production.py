"""EIA shale gas production by formation from the keyless STEO bulk file https://www.eia.gov/opendata/bulk/STEO.zip.
Agents (Bcf/d, monthly): Agent_Prod_Appalachia = Marcellus (SNGPRMC) + Utica (SNGPRUA); Agent_Prod_Permian = SNGPRPM;
Agent_Prod_Haynesville = SNGPRHA; Agent_Prod_EagleFord = SNGPREF; Agent_Prod_Bakken = SNGPRBK; Agent_Prod_DJBasin = SNGPRNI
(Niobrara-Codell). These are EIA ESTIMATES of shale production by play (recent months are modelled and get revised), and
only history is loaded: any month at or after the retrieval month is skipped so no forecast is ever stored as an observation.
PIT: month M is treated as published with the STEO released in month M+1, taken conservatively as the 15th at 17:00Z.
The bulk file carries only the LATEST vintage, so first-load history uses that rule and cannot reproduce past revisions.
On later runs a changed value is stored as a NEW vintage available at retrieval time."""
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

URL = "https://www.eia.gov/opendata/bulk/STEO.zip"
AGENTS = {
    "Agent_Prod_Appalachia": ["STEO.SNGPRMC.M", "STEO.SNGPRUA.M"],
    "Agent_Prod_Permian": ["STEO.SNGPRPM.M"],
    "Agent_Prod_Haynesville": ["STEO.SNGPRHA.M"],
    "Agent_Prod_EagleFord": ["STEO.SNGPREF.M"],
    "Agent_Prod_Bakken": ["STEO.SNGPRBK.M"],
    "Agent_Prod_DJBasin": ["STEO.SNGPRNI.M"],
}


def fetch(url):
    r = httpx.get(url, timeout=180, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def parse(body: bytes) -> dict:
    need = {s for v in AGENTS.values() for s in v}
    out = {}
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        with z.open("STEO.txt") as f:
            for raw in f:
                line = raw.decode("utf-8", "ignore")
                if "STEO.SNGPR" not in line[:40]:
                    continue
                d = json.loads(line)
                if d.get("series_id") in need:
                    if d.get("units") != "billion cubic feet per day" or d.get("f") != "M":
                        raise ValueError(f"unexpected units/frequency for {d['series_id']}")
                    out[d["series_id"]] = {p: float(v) for p, v in d["data"] if v is not None}
    missing = need - set(out)
    if missing:
        raise ValueError(f"series missing from STEO bulk file: {sorted(missing)}")
    return out


def release_ts(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[4:]) + 1
    if m == 13:
        y, m = y + 1, 1
    return f"{y:04d}-{m:02d}-15T17:00:00Z"


def collect(conn, fetcher=fetch, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    this_month = now.strftime("%Y%m")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"STEO.zip HTTP {status}")
    h = ingest.archive_payload(conn, body, "eia_steo_bulk", URL, status, retrieved, ctype)
    data = parse(body)
    out = []
    for agent, sids in AGENTS.items():
        months = set.intersection(*[set(data[s]) for s in sids])
        known = {r[1][:7].replace("-", ""): r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [agent], measured_only=False)}
        new = 0
        for ym in sorted(m for m in months if m < this_month):          # history only: never a forecast month
            val = round(sum(data[s][ym] for s in sids), 4)
            prev = known.get(ym)
            if prev is not None and abs(prev - val) < 1e-9:
                continue
            revised = prev is not None
            avail = retrieved if revised else release_ts(ym)
            if not revised and avail > retrieved:                       # released rule says "not public yet" -> wait
                continue
            new += int(ingest.record_observation(
                conn, agent_id=agent, target_timestamp=f"{ym[:4]}-{ym[4:]}-01T00:00:00Z", available_timestamp=avail, value=val,
                source_id="eia_steo_bulk", source_url=URL, unit="Bcf/d (monthly average)", retrieved_timestamp=retrieved,
                revision_timestamp=retrieved if revised else None, geographic_scope=agent.replace("Agent_Prod_", ""),
                series_id="+".join(s.split(".")[1] for s in sids), raw_payload_hash=h, extraction_version="steo_production/1",
                quality_status="revision_vintage" if revised else "source_estimate_latest_vintage_release_rule_assumed",
                provenance="measured"))
        conn.commit()
        out.append({"agent": agent, "observations_new": new})
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(collect(sqlite3.connect(db)))
