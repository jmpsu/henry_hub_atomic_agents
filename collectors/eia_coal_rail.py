"""EIA coal transportation rates to the electric power sector (keyless XLSX):
https://www.eia.gov/coal/transportationrates/excel/Table%201_Nominal.xlsx  (Table 1, "Railroad" block)
Agent_Coal_Rail_TransportRate <- average RAILROAD transportation cost of coal delivered to power plants, nominal USD per ton,
annual (EIA-923 based). Annual figure stored with target = 1 January of the year.
PIT assumption (documented, conservative; EIA does not print a release date on the page): year Y is public by
31 December of Y+1 at 16:00Z. A later changed value is stored as a new vintage available at retrieval time.
Parsed with the standard library (the XLSX is a zip of XML); the layout is checked and any change raises."""
import io
import os
import re
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

URL = "https://www.eia.gov/coal/transportationrates/excel/Table%201_Nominal.xlsx"
AGENT = "Agent_Coal_Rail_TransportRate"


def fetch(url):
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def parse(body: bytes) -> dict:
    """{year: USD/ton} from the Railroad block of Table 1."""
    z = zipfile.ZipFile(io.BytesIO(body))
    ss = [re.sub(r"<[^>]+>", "", s) for s in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    sheet = z.read("xl/worksheets/sheet1.xml").decode()
    rows = []
    for r in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        cells = {col: (ss[int(v)] if t == "s" and v else v) for col, t, v in
                 re.findall(r'<c r="([A-Z]+)\d+"(?:[^>]*?t="(\w+)")?[^>]*?(?:/>|>(?:<f>[^<]*</f>)?(?:<v>([^<]*)</v>)?</c>)', r)}
        rows.append(cells)
    title = " ".join((r.get("A") or "") for r in rows[:2])
    if "Average Transportation and Delivered Costs of Coal" not in title or "nominal dollars per ton" not in title:
        raise ValueError("unexpected Table 1 title (layout change?)")
    header = next((r for r in rows if (r.get("A") or "").strip() == "Year"), None)
    if not header or "Transportation Cost" not in (header.get("B") or ""):
        raise ValueError("unexpected Table 1 header (layout change?)")
    out, block = {}, None
    for r in rows:
        a = (r.get("A") or "").strip()
        if a in ("Railroad", "Waterway", "Truck") or a.startswith("US Total"):
            block = a
            continue
        if block == "Railroad" and a.isdigit() and r.get("B") not in (None, "", "W"):
            out[int(a)] = float(r["B"])
    if len(out) < 5:
        raise ValueError("railroad block not found or too short")
    return out


def collect(conn, fetcher=fetch, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"EIA coal transportation HTTP {status}")
    h = ingest.archive_payload(conn, body, "eia_coal_transportation", URL, status, retrieved, ctype)
    known = {r[1][:4]: r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [AGENT], measured_only=False)}
    new = 0
    for y, v in sorted(parse(body).items()):
        v = round(v, 4)
        prev = known.get(str(y))
        if prev is not None and abs(prev - v) < 1e-9:
            continue
        revised = prev is not None
        avail = retrieved if revised else f"{y + 1}-12-31T16:00:00Z"
        if not revised and avail > retrieved:
            continue
        new += int(ingest.record_observation(
            conn, agent_id=AGENT, target_timestamp=f"{y}-01-01T00:00:00Z", available_timestamp=avail, value=v, source_id="eia_coal_transportation",
            source_url=URL, unit="USD/ton (annual average, nominal)", retrieved_timestamp=retrieved, revision_timestamp=retrieved if revised else None,
            geographic_scope="USA, electric power sector, railroad", series_id="coal_transport_table1.railroad", raw_payload_hash=h,
            extraction_version="eia_coal_rail/1", quality_status="revision_vintage" if revised else "annual_availability_assumed_year_end_plus_one",
            provenance="measured"))
    conn.commit()
    return [{"agent": AGENT, "observations_new": new}]


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(collect(sqlite3.connect(db)))
