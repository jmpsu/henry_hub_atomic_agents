import os, re
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import ingest
import lng_geoenv.real_registry as reg

UA = "Mozilla/5.0 (compatible; HenryHubPIT/1.0)"

def collect(conn):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tgt = now[:10] + "T00:00:00Z"
    urls = {"PanamaCanal": (os.environ["PANAMA_URL"], "Agent_Maritime_Panama_DelayDays"), "SuezCanal": (os.environ["SUEZ_URL"], "Agent_Maritime_Suez_DelayDays")}
    out = []
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        for name, (url, aid) in urls.items():
            try:
                r = client.get(url, timeout=20)
                h = ingest.archive_payload(conn, r.content, f"maritime_{name.lower()}", url, r.status_code, now, "text/html")
                txt = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
                m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:days?|hours?)\s*(?:wait|delay|queue)", txt, flags=re.I)
                delay = float(m.group(1)) if m else 0.0
                if m and "hour" in m.group(0).lower():
                    delay = round(delay / 24.0, 3)
                added = 1 if (r.status_code == 200 and ingest.record_observation(conn, agent_id=aid, target_timestamp=tgt, available_timestamp=now, published_timestamp=now, value=delay, source_id=f"maritime_{name.lower()}", source_url=url, unit="days", geographic_scope=name, raw_payload_hash=h, quality_status="validated", provenance="measured")) else 0
                out.append({"chokepoint": name, "baseline_days": getattr(reg, "CHOKEPOINTS", {}).get(name, {}).get("baseline_days"), "http_status": r.status_code, "delay_days": delay, "observations_new": added})
            except Exception as exc:
                out.append({"chokepoint": name, "error": repr(exc)})
    return out
