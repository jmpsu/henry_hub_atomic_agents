"""NOAA CPC 6-10 / 8-14 day prognostic discussion (keyless HTML, issued daily ~15:00 ET):
https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html

Unstructured source for the knowledge library (Section 5.1 'NOAA weather forecasts and discussions'). Each issuance is
stored once in `documents` with the source's issuance time as published_timestamp/available_timestamp (the text is public
from that moment), the retrieval time kept separately, and the original HTML archived in raw/. The text is the forecaster's
narrative; it is a source document, not a measured observation."""
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

URL = "https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html"
TZ = {"EST": -5, "EDT": -4}


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, domain TEXT, source_id TEXT, source_url TEXT, title TEXT, body TEXT,
        published_timestamp TEXT, available_timestamp TEXT, retrieved_timestamp TEXT, raw_payload_hash TEXT, extraction_version TEXT, provenance TEXT)""")


def fetch(url):
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def parse(text: str) -> dict:
    pre = re.findall(r"<pre[^>]*>(.*?)</pre>", text, re.S | re.I)
    if len(pre) != 1:
        raise ValueError(f"expected one <pre> block, found {len(pre)}")
    body = html.unescape(re.sub(r"<[^>]+>", "", pre[0])).replace("\r", "")
    body = "\n".join(l.rstrip() for l in body.strip().splitlines())
    if not re.match(r"^Prognostic Discussion for 6 to 10 and 8 to 14 Day Outlooks\s*$", body.splitlines()[0] if body else "", re.I):
        raise ValueError("unexpected discussion header")
    m = re.search(r"^(\d{1,4}(?::\d{2})?) (AM|PM) (EST|EDT) \w{3} (\w+) (\d{1,2}) (\d{4})\s*$", body, re.M)
    if not m:
        raise ValueError("issuance time line not found")
    hhmm, ampm, tz, mon, day, year = m.groups()
    if ":" in hhmm:
        parts = hhmm.split(":")
        hh, mm = int(parts[0]), int(parts[1])
    elif len(hhmm) > 2:
        hh, mm = int(hhmm) // 100, int(hhmm) % 100
    else:
        hh, mm = int(hhmm), 0
    hh = hh % 12 + (12 if ampm == "PM" else 0)
    local = datetime.strptime(f"{year} {mon} {day} {hh}:{mm}", "%Y %B %d %H:%M")
    issued = (local - timedelta(hours=TZ[tz])).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p6 = re.search(r"6-10 Day Outlook for (.+)$", body, re.I | re.M)
    p8 = re.search(r"8-14 Day Outlook for (.+)$", body, re.I | re.M)
    return {"issued": issued, "body": body, "period_6_10": p6.group(1) if p6 else None, "period_8_14": p8.group(1) if p8 else None}


def collect(conn, fetcher=fetch, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    status, body, ctype = fetcher(URL)
    if status != 200:
        raise RuntimeError(f"CPC discussion HTTP {status}")
    ensure(conn)
    h = ingest.archive_payload(conn, body, "noaa_cpc_610_discussion", URL, status, retrieved, ctype)
    d = parse(body.decode("utf-8", "ignore"))
    if d["issued"] > retrieved:
        raise ValueError("issuance time is in the future; refusing (clock or parse error)")
    did = f"cpc610_{d['issued']}"
    title = f"CPC 6-10/8-14 day discussion issued {d['issued'][:16].replace('T', ' ')}Z (6-10: {d['period_6_10']}; 8-14: {d['period_8_14']})"
    cur = conn.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (did, "noaa_discussion", "noaa_cpc_610_discussion", URL, title, d["body"], d["issued"], d["issued"], retrieved, h,
                        "noaa_cpc_discussion/1", "source_document"))
    conn.commit()
    return {"document": did, "new": cur.rowcount == 1, "issued": d["issued"], "chars": len(d["body"]), "raw_payload_hash": h}


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(collect(sqlite3.connect(db)))
