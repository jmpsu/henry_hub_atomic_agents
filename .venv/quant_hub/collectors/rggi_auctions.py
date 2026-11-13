"""RGGI quarterly CO2 allowance auction clearing prices (HTML table, keyless):
https://www.rggi.org/auctions/auction-results/prices-volumes  -> Agent_Power_CO2_AllowancePrice (USD/short ton).
Quarterly clearing price only (the roster's 'secondary price' is NOT covered). PIT assumption (documented, conservative):
results public the day AFTER the auction at 16:00Z. Target = auction date."""
import html
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

URL = "https://www.rggi.org/auctions/auction-results/prices-volumes"
AGENT = "Agent_Power_CO2_AllowancePrice"
EXPECTED = ["Auction", "Date", "Quantity Offered", "CCR Sold", "Quantity Sold", "Clearing Price", "Total Proceeds"]


def fetch(url):
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def parse(text: str) -> list:
    rows = [[re.sub(r"<[^>]+>", "", html.unescape(c)).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)]
    if not rows or rows[0][:7] != EXPECTED:
        raise ValueError(f"unexpected RGGI table header: {rows[0] if rows else None}")
    out = []
    for r in rows[1:]:
        m = re.fullmatch(r"\$([\d.,]+)", r[5]) if len(r) >= 7 else None
        if not m or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[1]):
            continue
        out.append((r[0], r[1], float(m.group(1).replace(",", ""))))
    if not out:
        raise ValueError("no RGGI auction rows parsed")
    return out


def collect(conn, fetcher=fetch, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"RGGI HTTP {status}")
    h = ingest.archive_payload(conn, body, "rggi_auction_results", URL, status, retrieved, ctype)
    new = 0
    for auction, day, price in parse(body.decode("utf-8", "ignore")):
        d = datetime.strptime(day, "%Y-%m-%d")
        avail = (d + timedelta(days=1, hours=16)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new += int(ingest.record_observation(
            conn, agent_id=AGENT, target_timestamp=day + "T00:00:00Z", available_timestamp=avail, value=price,
            source_id="rggi_auction_results", source_url=URL, unit="USD/short ton", retrieved_timestamp=retrieved,
            geographic_scope="RGGI states", series_id=auction.replace(" ", "_").upper(), raw_payload_hash=h,
            extraction_version="rggi_auctions/1", quality_status="validated_availability_assumed_d+1", provenance="measured"))
    conn.commit()
    return [{"agent": AGENT, "observations_new": new}]


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(collect(sqlite3.connect(db)))
