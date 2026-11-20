"""EIA monthly LNG exports by terminal and pipeline trade at border points, from the keyless bulk file https://www.eia.gov/opendata/bulk/NG.zip (NG.txt).

These fill the dashboard's empty LNG and border-meter slots with OFFICIAL data, but they are NOT the daily meters the roster describes:
  * unit is MMcf per MONTH, stored as published (no conversion, no daily estimate);
  * LNG rows are total exports from the terminal (all destinations), not feedgas nominations;
  * border rows are EIA border-crossing points. Eastport (Kingsgate), Noyes (Emerson) and Waddington are the named crossings. NET Mexico and
    Valley Crossing have no EIA series of their own, so the nearest published Mexico crossing is used (Rio Grande, Brownsville) and the roster text says
    so: that mapping is an inference, not a measurement of those pipelines.
Agents therefore get their own ids (Agent_LNGExports_*, Agent_BorderFlow_*); the roster's daily Agent_Flow_* / Agent_LNG_*_Flow stay pending.
PIT: month M is treated as published at the end of month M+2 16:00Z (same rule as eia_ng_monthly, conservative). The bulk file carries only the latest vintage, so
first-load history uses that rule and cannot reproduce past revisions; on later runs a changed value is stored as a NEW vintage available at retrieval time."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
from collectors.eia_ng_monthly import URL, fetch, release_ts  # noqa: E402

FIRST = "201501"
UNIT = "MMcf/month"
SERIES = {  # agent_id -> EIA series id
    "Agent_LNGExports_SabinePass": "NG.NGM_EPG0_ENG_YSPL-Z00_MMCF.M",
    "Agent_LNGExports_CorpusChristi": "NG.NGM_EPG0_ENG_YCRP-Z00_MMCF.M",
    "Agent_LNGExports_Freeport": "NG.NGM_EPG0_ENG_YFPT-Z00_MMCF.M",
    "Agent_LNGExports_Cameron": "NG.NGM_EPG0_ENG_YCAM-Z00_MMCF.M",
    "Agent_LNGExports_CalcasieuPass": "NG.NGM_EPG0_ENG_YCCPL-Z00_MMCF.M",
    "Agent_LNGExports_CovePoint": "NG.NGM_EPG0_ENG_YCPT-Z00_MMCF.M",
    "Agent_LNGExports_ElbaIsland": "NG.NGM_EPG0_ENG_YELBA-Z00_MMCF.M",
    "Agent_LNGExports_Plaquemines": "NG.NGM_EPG0_ENG_YPLAQ-Z00_MMCF.M",
    "Agent_BorderFlow_Eastport_FromCanada": "NG.NA1277_YEPRT-NCA_2.M",
    "Agent_BorderFlow_Noyes_FromCanada": "NG.NA1277_YNOYS-NCA_2.M",
    "Agent_BorderFlow_Waddington_FromCanada": "NG.NA1277_YWADD-NCA_2.M",
    "Agent_BorderFlow_RioGrande_ToMexico": "NG.NGM_EPG0_ENP_YGRAN-NMX_MMCF.M",
    "Agent_BorderFlow_Brownsville_ToMexico": "NG.NGM_EPG0_ENP_YBROWN-NMX_MMCF.M",
}


def parse(body: bytes) -> dict:
    """{series_id: {'YYYYMM': MMcf}} for the needed series; raises if one is missing or has unexpected units/frequency."""
    need = set(SERIES.values())
    out = {}
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        for line in z.read("NG.txt").decode().splitlines():
            if not line.startswith('{"series_id"'):
                continue
            d = json.loads(line)
            if d["series_id"] in need:
                if d.get("units") != "Million Cubic Feet" or d.get("f") != "M":
                    raise ValueError(f"unexpected units/frequency for {d['series_id']}: {d.get('units')}/{d.get('f')}")
                out[d["series_id"]] = {p: float(v) for p, v in d["data"] if v is not None}
    missing = need - set(out)
    if missing:
        raise ValueError(f"series missing from bulk file: {sorted(missing)}")
    return out


def collect(conn, fetcher=fetch, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"NG.zip HTTP {status}")
    h = ingest.archive_payload(conn, body, "eia_ng_bulk", URL, status, retrieved, ctype)
    data = parse(body)
    out = []
    for agent, sid in SERIES.items():
        months = {m: v for m, v in data[sid].items() if m >= FIRST}
        known = {r[1][:7].replace("-", ""): r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [agent], measured_only=False)}
        new = 0
        for ym in sorted(months):
            val, prev = months[ym], known.get(ym)
            if prev is not None and abs(prev - val) < 1e-9:
                continue
            revised = prev is not None
            new += int(ingest.record_observation(
                conn, agent_id=agent, target_timestamp=f"{ym[:4]}-{ym[4:]}-01T00:00:00Z",
                available_timestamp=retrieved if revised else release_ts(ym), value=val, source_id="eia_ng_bulk", source_url=URL, unit=UNIT,
                retrieved_timestamp=retrieved, revision_timestamp=retrieved if revised else None, geographic_scope="USA", series_id=sid,
                raw_payload_hash=h, extraction_version="eia_ng_flows/1",
                quality_status="revision_vintage" if revised else "latest_vintage_release_rule_assumed", provenance="measured"))
        conn.commit()
        last = max(months) if months else None
        out.append({"agent": agent, "series": sid, "observations_new": new, "latest_month": last, "latest_mmcf": months.get(last)})
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    for r in collect(sqlite3.connect(db)):
        print(r)
