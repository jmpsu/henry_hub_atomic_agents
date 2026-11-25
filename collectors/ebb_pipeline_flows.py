import os, re
from datetime import datetime, timezone
import httpx, ingest
import lng_geoenv.real_registry as reg

UA = "Mozilla/5.0 (compatible; HenryHubPIT/1.0)"

def collect(conn):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        for pipe in ("KMLP", "EEC", "NGPL", "TGP"):
            url = os.environ["KM_BASE"] + pipe
            try:
                r = client.get(url, timeout=20)
                h = ingest.archive_payload(conn, r.content, f"ebb_{pipe.lower()}", url, r.status_code, now, "text/html")
                vals = [float(m.replace(",", "")) for m in re.findall(r">([0-9]{1,3}(?:,[0-9]{3})+)</", r.text)]
                out.append({"pipeline": pipe, "http_status": r.status_code, "meters_parsed": len(vals), "raw_payload_hash": h})
            except Exception as exc:
                out.append({"pipeline": pipe, "error": repr(exc)})
    out.append({"terminals": len(getattr(reg, "US_LNG_TERMINALS", {})), "border_meters": len(getattr(reg, "BORDER_FLOW_METERS", {}))})
    return out
