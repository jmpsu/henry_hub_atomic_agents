"""ECMWF IFS HRES 00z forecast HDD (Agent_ECMWF_00z_HDD_Day1..9) from ECMWF's keyless open-data archive on AWS S3.
Same approximate method as gfs_hdd (40 metros, population-weighted, 06Z..06Z daily-mean 2t). LIMIT: the open-data HRES run
ends at step 240, so Day 10 would need step 246 and Days 11-15 do not exist in this feed -> those agents are NOT implemented.
PIT: available = S3 Last-Modified of the fetched GRIB; forecasts recorded as issued, never revised."""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
from collectors.gfs_hdd import METROS, weighted_hdd  # noqa: E402

BASE = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/{d}/00z/ifs/0p25/oper/{d}000000-{s}h-oper-fc"
MAX_STEP = 240


def parse_index(text: str, param: str = "2t") -> tuple:
    for line in text.splitlines():
        if line.strip():
            j = json.loads(line)
            if j.get("param") == param and j.get("levtype", "sfc") == "sfc":
                return j["_offset"], j["_offset"] + j["_length"] - 1
    raise ValueError(f"{param} not in ECMWF index")


def read_metro_temps(grib_bytes: bytes) -> list:
    import numpy as np
    import pygrib
    with tempfile.NamedTemporaryFile(suffix=".grib2") as f:
        f.write(grib_bytes); f.flush()
        msg = pygrib.open(f.name).message(1)
        lats, lons = msg.latlons()
        la, lo, vals = lats[:, 0], lons[0, :] % 360, msg.values
        out = []
        for lat, lon, _ in METROS:
            out.append(float(vals[int(np.abs(la - lat).argmin()), int(np.abs(lo - (lon % 360)).argmin())]))
        return out


def collect(conn, now: datetime = None, days=range(1, 10)) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    with httpx.Client(timeout=90) as c:
        d = next((dd for dd in ((now - timedelta(days=b)).strftime("%Y%m%d") for b in (0, 1, 2))
                  if c.get(BASE.format(d=dd, s=24) + ".index").status_code == 200), None)
        if not d:
            raise RuntimeError("no ECMWF 00z run found in last 3 days")
        init = datetime.strptime(d, "%Y%m%d").replace(tzinfo=timezone.utc)
        for n in days:
            steps = [24 * n - 12, 24 * n - 6, 24 * n, 24 * n + 6]
            if max(steps) > MAX_STEP:
                raise ValueError(f"Day{n} needs step {max(steps)} > {MAX_STEP}: not in open-data HRES")
            temps, mods, raw = [], [], b""
            for s in steps:
                url = BASE.format(d=d, s=s)
                a, b = parse_index(c.get(url + ".index").text)
                r = c.get(url + ".grib2", headers={"Range": f"bytes={a}-{b}"})
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"ECMWF range HTTP {r.status_code}")
                raw += r.content
                mods.append(parsedate_to_datetime(r.headers["last-modified"]) if r.headers.get("last-modified") else now)
                temps.append(read_metro_temps(r.content))
            value = weighted_hdd([sum(col) / 4 for col in zip(*temps)])
            avail = max(mods).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            h = ingest.archive_payload(conn, raw, "ecmwf_open_data", BASE.format(d=d, s=24 * n) + ".grib2", 206, retrieved, "application/grib2")
            ok = ingest.record_observation(
                conn, agent_id=f"Agent_ECMWF_00z_HDD_Day{n}", target_timestamp=(init + timedelta(days=n - 1)).strftime("%Y-%m-%dT00:00:00Z"),
                available_timestamp=avail, value=round(value, 3), source_id="ecmwf_open_data", source_url=BASE.format(d=d, s=24 * n) + ".grib2",
                unit="approx. population-weighted HDD (40 metros)", retrieved_timestamp=retrieved, published_timestamp=avail,
                geographic_scope="CONUS approx: 40 metros, population-weighted (not CPC method)", series_id=f"ECMWF_00z_HDD_DAY{n}",
                raw_payload_hash=h, extraction_version="ecmwf_hdd/1", quality_status="validated_approximation", provenance="measured")
            out.append({"agent": f"Agent_ECMWF_00z_HDD_Day{n}", "new": int(ok), "hdd": round(value, 2), "init": d})
        conn.commit()
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    for r in collect(sqlite3.connect(db)):
        print(r)
