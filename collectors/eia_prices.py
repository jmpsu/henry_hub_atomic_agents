"""EIA daily Henry Hub spot + NYMEX futures contracts 1-4 (keyless XLS).
- Spot: current (last obs verified 2026-11-11). Agent id Agent_HH_Spot_EIA (EIA/Refinitiv spot; NOT the NGI index).
- Futures C1..C4 -> Agent_HH_M1..M4: EIA's series ENDS 2024-04-05 (source discontinued) -> historical backtests only.
PIT assumption (documented): a daily settle is public the evening of its trade date, so available = trade date 21:00Z.
Prices are not revised after publication; this is the standard close-of-day backtest assumption."""
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import xlrd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

SERIES = {  # xls name -> (agent_id, sourcekey, unit, discontinued)
    "RNGWHHDd": ("Agent_HH_Spot_EIA", "RNGWHHD", "USD/MMBtu", False),
    "RNGC1d": ("Agent_HH_M1", "RNGC1", "USD/MMBtu", True),
    "RNGC2d": ("Agent_HH_M2", "RNGC2", "USD/MMBtu", True),
    "RNGC3d": ("Agent_HH_M3", "RNGC3", "USD/MMBtu", True),
    "RNGC4d": ("Agent_HH_M4", "RNGC4", "USD/MMBtu", True),
}
URL = "https://www.eia.gov/dnav/ng/hist_xls/{name}.xls"


def read_xls(body: bytes) -> list:
    wb = xlrd.open_workbook(file_contents=body)
    s = wb.sheet_by_name("Data 1")
    if s.cell_value(2, 0) != "Date":
        raise ValueError("unexpected EIA xls layout: 'Date' header not at row 3")
    out = []
    for r in range(3, s.nrows):
        if s.cell_type(r, 0) == 3 and s.cell_type(r, 1) == 2:
            out.append((xlrd.xldate_as_datetime(s.cell_value(r, 0), wb.datemode).date(), float(s.cell_value(r, 1))))
    if not out:
        raise ValueError("no observations parsed")
    return out


def fetch(url):
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def load(conn, name, rows, raw_hash, retrieved, url) -> int:
    agent, key, unit, discontinued = SERIES[name]
    known = {r[1][:10]: r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [agent], measured_only=False)}
    new = 0
    for day, val in rows:
        if known.get(day.isoformat()) == val:
            continue
        revised = day.isoformat() in known   # value differs from the stored vintage -> new vintage, available now
        avail = retrieved if revised else (datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=21)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new += int(ingest.record_observation(
            conn, agent_id=agent, target_timestamp=day.isoformat() + "T00:00:00Z", available_timestamp=avail, value=val,
            source_id="eia_dnav_ng", source_url=url, unit=unit, retrieved_timestamp=retrieved, geographic_scope="Henry Hub, LA",
            series_id=key, raw_payload_hash=raw_hash, extraction_version="eia_prices/1", revision_timestamp=retrieved if revised else None,
            quality_status="revision_vintage" if revised else "historical_only_source_discontinued_2024-04" if discontinued else "validated_availability_assumed_close",
            provenance="measured"))
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
        h = ingest.archive_payload(conn, body, "eia_dnav_ng", url, status, retrieved, ctype)
        n = load(conn, name, read_xls(body), h, retrieved, url)
        conn.commit()
        out.append({"agent": SERIES[name][0], "observations_new": n})
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    for r in collect(sqlite3.connect(db)):
        print(r)
