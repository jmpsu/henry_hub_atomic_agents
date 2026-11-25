import os, re
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup
import ingest

UA = "Mozilla/5.0 (compatible; HenryHubPIT/1.0)"
BASIS_SYMS = {"Agent_NATGAS_Waha_Basis": ("WM=F", "Permian"), "Agent_Houston_ShipChannel_Basis": ("H7=F", "HSC"), "Agent_NATGAS_TranscoZone6_Basis": ("7F=F", "TZ6"), "Agent_NATGAS_AECO_Basis": ("NGA=F", "AECO"), "Agent_LNG_JKM_Forward": ("JKM=F", "JKM")}

def collect(conn):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tgt = now[:10] + "T00:00:00Z"
    out = []
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        r = client.get(os.environ["NG_WEEKLY_URL"], timeout=20)
        h = ingest.archive_payload(conn, r.content, "eia_ng_weekly", os.environ["NG_WEEKLY_URL"], 200, now, "text/html")
        txt = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
        hubs = {}
        for k, pat in [("HH", r"Henry Hub[^0-9\n]{0,40}\$?([0-9]+\.[0-9]{2})"), ("HSC", r"Houston Ship Channel[^0-9\n]{0,60}\$?([0-9]+\.[0-9]{2})"), ("TZ6", r"Transco Zone 6[^0-9\n]{0,60}\$?([0-9]+\.[0-9]{2})"), ("Waha", r"Waha[^0-9\n]{0,60}\$?([0-9]+\.[0-9]{2})"), ("JKM", r"(?:East Asia|JKM)[^0-9\n]{0,80}\$?([0-9]+\.[0-9]{2})")]:
            ms = re.findall(pat, txt, flags=re.I)
            if ms:
                hubs[k] = float(ms[-1])
        hh = hubs.get("HH")
        writes = []
        if "Waha" in hubs:
            writes.append(("Agent_Gas_Waha_Spot", hubs["Waha"], "Permian"))
            if hh is not None:
                writes.append(("Agent_NATGAS_Waha_Basis", round(hubs["Waha"] - hh, 4), "Permian"))
        if "HSC" in hubs and hh is not None:
            writes.append(("Agent_Houston_ShipChannel_Basis", round(hubs["HSC"] - hh, 4), "HSC"))
        if "TZ6" in hubs and hh is not None:
            writes.append(("Agent_NATGAS_TranscoZone6_Basis", round(hubs["TZ6"] - hh, 4), "TZ6"))
        if "JKM" in hubs:
            writes.append(("Agent_LNG_JKM_Forward", hubs["JKM"], "JKM"))
        for aid, val, scope in writes:
            added = 1 if ingest.record_observation(conn, agent_id=aid, target_timestamp=tgt, available_timestamp=now, published_timestamp=now, value=val, source_id="eia_ng_weekly", source_url=os.environ["NG_WEEKLY_URL"], unit="USD/MMBtu", geographic_scope=scope, raw_payload_hash=h, quality_status="validated", provenance="measured") else 0
            out.append({"agent": aid, "value": val, "observations_new": added})
        for aid, (sym, scope) in BASIS_SYMS.items():
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
                        qh = ingest.archive_payload(conn, yr.content, "cme_basis_delayed", url, 200, now, "application/json")
                        if ingest.record_observation(conn, agent_id=aid, target_timestamp=dt, available_timestamp=now, published_timestamp=dt, value=round(float(p), 4), source_id="cme_basis_delayed", source_url=url, unit="USD/MMBtu", geographic_scope=scope, raw_payload_hash=qh, quality_status="delayed_quote_unverified", provenance="measured"):
                            added = 1
            out.append({"agent": aid, "observations_new": added})
    return out
