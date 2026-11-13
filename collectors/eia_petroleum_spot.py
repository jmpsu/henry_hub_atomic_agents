"""EIA daily petroleum spot prices (keyless XLS, same layout as the natural-gas price files).
- Agent_Crude_WTI_Spot: Cushing OK WTI spot FOB, USD/bbl (RWTC).
- Agent_NGL_MontBelvieu_Propane: Mont Belvieu TX propane spot FOB, stored in cents/gal (source is USD/gal x 100).
EIA does NOT publish daily spot for ethane, butanes, natural gasoline or Conway, so those products have no collector here.
PIT assumption (documented): a daily price is public the evening of its trade date, so available = trade date 21:00Z.
A later changed value is stored as a new vintage available at retrieval time."""
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
from collectors.eia_prices import fetch, read_xls  # noqa: E402

SERIES = {  # xls name -> (agent_id, series key, unit, multiplier, scope)
    "RWTCd": ("Agent_Crude_WTI_Spot", "RWTC", "USD/bbl", 1.0, "Cushing, OK"),
    "EER_EPLLPA_PF4_Y44MB_DPGd": ("Agent_NGL_MontBelvieu_Propane", "EER_EPLLPA_PF4_Y44MB_DPG", "cents/gal", 100.0, "Mont Belvieu, TX"),
}
URL = "https://www.eia.gov/dnav/pet/hist_xls/{name}.xls"


def load(conn, name, rows, raw_hash, retrieved, url) -> int:
    agent, key, unit, mult, scope = SERIES[name]
    known = {r[1][:10]: r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [agent], measured_only=False)}
    new = 0
    for day, raw in rows:
        val = round(raw * mult, 4)
        prev = known.get(day.isoformat())
        if prev is not None and abs(prev - val) < 1e-9:
            continue
        revised = prev is not None
        avail = retrieved if revised else (datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=21)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new += int(ingest.record_observation(
            conn, agent_id=agent, target_timestamp=day.isoformat() + "T00:00:00Z", available_timestamp=avail, value=val,
            source_id="eia_dnav_pet", source_url=url, unit=unit, retrieved_timestamp=retrieved, geographic_scope=scope,
            series_id=key, raw_payload_hash=raw_hash, extraction_version="eia_petroleum_spot/1",
            revision_timestamp=retrieved if revised else None,
            quality_status="revision_vintage" if revised else "validated_availability_assumed_close", provenance="measured"))
    return new


def collect(conn, fetcher=fetch, now=None, only=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for name in (only or SERIES):
        url = URL.format(name=name)
        status, body, ctype = fetcher(url)
        if status != 200:
            raise RuntimeError(f"{name}: HTTP {status}")
        h = ingest.archive_payload(conn, body, "eia_dnav_pet", url, status, retrieved, ctype)
        n = load(conn, name, read_xls(body), h, retrieved, url)
        conn.commit()
        out.append({"agent": SERIES[name][0], "observations_new": n})
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    for r in collect(sqlite3.connect(db)):
        print(r)
