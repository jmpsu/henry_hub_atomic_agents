import csv, io, os, re
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import ingest

UA = "Mozilla/5.0 (compatible; HenryHubPIT/1.0)"
YAHOO_NGL = {"Agent_NGL_MontBelvieu_Ethane": "C0=F", "Agent_NGL_MontBelvieu_NormalButane": "D0=F", "Agent_NGL_MontBelvieu_Isobutane": "E0=F", "Agent_NGL_MontBelvieu_NatGasoline": "7Q=F"}

def collect(conn):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        r = client.get(os.environ["PROPANE_URL"], timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        new_c = 0
        for tr in soup.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if cells and any("conway" in c.lower() or "kansas" in c.lower() for c in cells):
                nums = [float(m.group(1)) for c in cells[1:] if (m := re.search(r"([0-9]+\.[0-9]+)", c.replace(",", "")))]
                if nums:
                    h = ingest.archive_payload(conn, r.content, "eia_weekly_propane", os.environ["PROPANE_URL"], 200, now, "text/html")
                    if ingest.record_observation(conn, agent_id="Agent_NGL_Conway_Propane", target_timestamp=now[:10]+"T00:00:00Z", available_timestamp=now, published_timestamp=now, value=round(nums[-1]*100.0, 4), source_id="eia_weekly_propane", source_url=os.environ["PROPANE_URL"], unit="cents/gal", geographic_scope="Conway, KS", raw_payload_hash=h, quality_status="validated", provenance="measured"):
                        new_c = 1
                    break
        out.append({"agent": "Agent_NGL_Conway_Propane", "observations_new": new_c})
        for aid, sym in YAHOO_NGL.items():
            url = f"{os.environ['YAHOO_BASE']}{sym}?range=5d&interval=1d"
            yr = client.get(url, timeout=15)
            added = 0
            if yr.status_code == 200:
                res = ((yr.json().get("chart") or {}).get("result") or [])
                if res:
                    meta = res[0].get("meta") or {}
                    p, ts = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
                    if p is not None and ts is not None:
                        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
                        val = round(float(p)*100.0, 4) if float(p) < 10.0 else round(float(p), 4)
                        h = ingest.archive_payload(conn, yr.content, "cme_ngl_delayed", url, 200, now, "application/json")
                        if ingest.record_observation(conn, agent_id=aid, target_timestamp=dt, available_timestamp=now, published_timestamp=dt, value=val, source_id="cme_ngl_delayed", source_url=url, unit="cents/gal", geographic_scope="Mont Belvieu, TX", raw_payload_hash=h, quality_status="delayed_quote_unverified", provenance="measured"):
                            added = 1
            out.append({"agent": aid, "observations_new": added})
        sr = client.get(os.environ["STEO_URL"], timeout=30)
        if sr.status_code == 200:
            rows = list(csv.reader(io.StringIO(sr.content.decode("utf-8", errors="replace"))))
            smap = {"NGETBUS": "Agent_NGL_MontBelvieu_Ethane", "NGPRBUS": "Agent_NGL_Conway_Propane", "NGBUBUS": "Agent_NGL_MontBelvieu_NormalButane", "NGIBBUS": "Agent_NGL_MontBelvieu_Isobutane", "NGPGBUS": "Agent_NGL_MontBelvieu_NatGasoline"}
            if len(rows) > 5:
                drow = rows[4]
                for row in rows[5:]:
                    if row and row[0].strip() in smap:
                        aid = smap[row[0].strip()]
                        for i in range(len(row)-1, 1, -1):
                            vs = row[i].strip()
                            if vs and vs not in ("--", "NA", "nan"):
                                try:
                                    v = float(vs)
                                    v = round(v*100.0, 4) if v < 10.0 else round(v, 4)
                                    m = re.search(r"(20\d{2})[^0-9]?(\d{2})", drow[i] if i < len(drow) else "")
                                    tgt = f"{m.group(1)}-{m.group(2)}-01T00:00:00Z" if m else now[:10]+"T00:00:00Z"
                                    h = ingest.archive_payload(conn, sr.content, "eia_steo_ngl", os.environ["STEO_URL"], 200, now, "text/csv")
                                    added = 1 if ingest.record_observation(conn, agent_id=aid, target_timestamp=tgt, available_timestamp=now, published_timestamp=tgt, value=v, source_id="eia_steo_ngl", source_url=os.environ["STEO_URL"], unit="cents/gal", geographic_scope="US Gulf Coast", raw_payload_hash=h, quality_status="validated", provenance="measured") else 0
                                    out.append({"agent": aid, "source": "eia_steo_ngl", "observations_new": added})
                                    break
                                except ValueError:
                                    pass
    return out
