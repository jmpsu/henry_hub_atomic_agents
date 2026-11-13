"""Interstate pipeline critical notices from Kinder Morgan's public informational postings (FERC-mandated, keyless):
https://pipeline2.kindermorgan.com/Notices/Notices.aspx?type=C&code=<TSP>

Each notice (maintenance, pipeline conditions/restrictions, force majeure, gas quality, OFOs...) is stored once in
`documents` (domain pipeline_notice) with the pipeline's posting time as published/available timestamp and the original
page archived in raw/. The page states its pipeline ("TSP Name"); a response for a different pipeline (the site falls back to
Tennessee Gas for unknown codes) is rejected. Times are posted in Central time (America/Chicago) and stored in UTC.
These are source documents, not measured observations. Fetched once per daily run per pipeline."""
import html
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
from collectors.noaa_cpc_discussion import ensure  # noqa: E402  (documents table)

URL = "https://pipeline2.kindermorgan.com/Notices/Notices.aspx?type=C&code={code}"
PIPELINES = {  # code -> exact TSP name printed on the page
    "TGP": "TENNESSEE GAS PIPELINE", "EPNG": "EL PASO NATURAL GAS CO. L.L.C.", "EEC": "ELBA EXPRESS", "NGPL": "NATURAL GAS PIPELINE CO.",
    "SNG": "SOUTHERN NATURAL GAS CO.", "CIG": "COLORADO INTERSTATE GAS CO.", "KMLP": "KM LOUISIANA PIPELINE",
}
CT = ZoneInfo("America/Chicago")


def fetch(url):
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def to_utc(s: str) -> str:
    return datetime.strptime(s, "%m/%d/%Y %I:%M:%S%p").replace(tzinfo=CT).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(text: str, code: str) -> list:
    m = re.search(r"TSP Name:\s*(?:<[^>]+>\s*)*([^<]+)", text)
    tsp = html.unescape(m.group(1)).strip() if m else None
    if tsp != PIPELINES[code]:
        raise ValueError(f"page is for {tsp!r}, expected {PIPELINES[code]!r} (wrong pipeline or layout change)")
    out = []
    for r in re.finditer(r'data-rowkey="\[(\d+)\]"(.*?)(?=data-rowkey="\[|\Z)', text, re.S):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r.group(2), re.S)]
        cells = [c for c in cells if c]
        if len(cells) < 7 or cells[5] != r.group(1):
            raise ValueError(f"unexpected notice row layout for {r.group(1)}: {cells[:7]}")
        ntype, sub, posted, eff, end, nid, subject = cells[:7]
        out.append({"id": nid, "type": ntype, "subtype": sub, "posted": to_utc(posted), "effective": to_utc(eff), "end": to_utc(end) if end else None,
                    "subject": subject, "force_majeure": "FORCE MAJEURE" in f"{ntype} {sub} {subject}".upper()})
    if not out:
        raise ValueError("no notices parsed (layout change?)")
    return out


def collect(conn, fetcher=fetch, now=None, codes=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ensure(conn)
    out = []
    for code in codes or PIPELINES:
        url = URL.format(code=code)
        status, body, ctype = fetcher(url)
        if status != 200:
            raise RuntimeError(f"{code}: HTTP {status}")
        h = ingest.archive_payload(conn, body, f"kinder_morgan_notices_{code.lower()}", url, status, retrieved, ctype)
        new = 0
        for n in parse(body.decode("utf-8", "ignore"), code):
            if n["posted"] > retrieved:
                continue
            title = f"{PIPELINES[code].title()} {n['type'].lower()}" + (f" / {n['subtype'].lower()}" if n["subtype"] != n["type"] else "") + f": {n['subject']}"
            body_txt = (f"{PIPELINES[code]} ({code}) critical notice {n['id']}. Type: {n['type']}; subtype: {n['subtype']}. Subject: {n['subject']}. "
                        f"Posted {n['posted']}, effective {n['effective']}" + (f", ends {n['end']}" if n["end"] else "") + "."
                        + (" FORCE MAJEURE." if n["force_majeure"] else ""))
            cur = conn.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (f"km_{code}_{n['id']}", "pipeline_notice", f"kinder_morgan_notices_{code.lower()}", url, title[:200], body_txt,
                                n["posted"], n["posted"], retrieved, h, "kinder_morgan_notices/1", "source_document"))
            new += cur.rowcount
        conn.commit()
        out.append({"pipeline": code, "documents_new": new})
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    print(collect(sqlite3.connect(db)))
