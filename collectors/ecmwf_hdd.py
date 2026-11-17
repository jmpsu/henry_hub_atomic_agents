"""ECMWF IFS HRES 00z forecast HDD (Agent_ECMWF_00z_HDD_Day1..14) from ECMWF's keyless open data.
Same approximate method as gfs_hdd (40 metros, population-weighted, daily mean of four 6-hourly 2t samples).
Limits (verified 2026-11-17 against the live feed): HRES open data runs to step 360 (6-hourly after step 240). Day n uses steps 24n-12, 24n-6, 24n, 24n+6,
so Day 14 (max step 342) is the last day with all four samples; Day 15 would need step 366, which does not exist, so Agent_ECMWF_00z_HDD_Day15 stays pending
(a 3-sample mean would drop the coldest sample and bias HDD low). The ensemble-mean product (enfo-em) does not exist in open data.
Hosts: ECMWF's own mirror first, then Google's, then the AWS bucket. The AWS bucket answers 503 SlowDown under load; a 5xx/429/timeout is retried and then falls
through to the next mirror, and only a 404 on every mirror means "not published yet". Never reported as "no run found" when the service was merely unavailable.
PIT: available = the GRIB's Last-Modified (falls back to the retrieval time); forecasts recorded as issued, never revised."""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
from runtime_paths import scratch_file  # noqa: E402
from collectors.gfs_hdd import METROS, weighted_hdd  # noqa: E402

MIRRORS = [
    "https://data.ecmwf.int/forecasts/{d}/00z/ifs/0p25/oper/{d}000000-{s}h-oper-fc",
    "https://storage.googleapis.com/ecmwf-open-data/{d}/00z/ifs/0p25/oper/{d}000000-{s}h-oper-fc",
    "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/{d}/00z/ifs/0p25/oper/{d}000000-{s}h-oper-fc",
]
BASE = MIRRORS[0]
MAX_STEP = 360
DAYS = range(1, 15)
RETRYABLE = {429, 500, 502, 503, 504}


class NotPublished(RuntimeError):
    """Every mirror answered 404: the file does not exist (yet)."""


class Unavailable(RuntimeError):
    """No mirror produced the file and at least one failure was a service error, not a 404."""


def fetch(client, d: str, step: int, ext: str, headers=None, sleep=time.sleep, tries: int = 2):
    """GET {d}/{step}h{ext} from the first mirror that serves it. 404 moves to the next mirror; 5xx/429/timeouts are retried then move on."""
    seen = []
    for tpl in MIRRORS:
        url = tpl.format(d=d, s=step) + ext
        for attempt in range(tries):
            try:
                r = client.get(url, headers=headers or {})
            except Exception as exc:  # noqa: BLE001  timeouts and connection errors are service errors
                seen.append(f"{url.split('/')[2]} {type(exc).__name__}")
                if attempt + 1 < tries:
                    sleep(1.5)
                continue
            if r.status_code in (200, 206):
                return r, url
            seen.append(f"{url.split('/')[2]} HTTP {r.status_code}")
            if r.status_code == 404:
                break
            if r.status_code in RETRYABLE and attempt + 1 < tries:
                sleep(1.5)
                continue
            break
    if seen and all(x.endswith("HTTP 404") for x in seen):
        raise NotPublished(f"step {step} for {d}: " + "; ".join(seen))
    raise Unavailable(f"step {step} for {d}: " + "; ".join(seen))


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
    with scratch_file(".grib2", grib_bytes) as grib_path:   # pygrib needs a real file; kept under runtime/scratch/
        msg = pygrib.open(grib_path).message(1)
        lats, lons = msg.latlons()
        la, lo, vals = lats[:, 0], lons[0, :] % 360, msg.values
        out = []
        for lat, lon, _ in METROS:
            out.append(float(vals[int(np.abs(la - lat).argmin()), int(np.abs(lo - (lon % 360)).argmin())]))
        return out


def collect(conn, now: datetime = None, days=DAYS, client=None, sleep=time.sleep) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    own = client is None
    client = client or httpx.Client(timeout=90, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d, problems = None, []
        for back in (0, 1, 2):
            dd = (now - timedelta(days=back)).strftime("%Y%m%d")
            try:
                fetch(client, dd, 24, ".index", sleep=sleep)
                d = dd
                break
            except NotPublished as e:
                problems.append(f"{dd}: not published ({e})")
            except Unavailable as e:
                problems.append(f"{dd}: service unavailable ({e})")
        if not d:
            kind = "service unavailable" if any("service unavailable" in p for p in problems) else "not published"
            raise RuntimeError(f"no ECMWF 00z run usable in the last 3 days ({kind}): " + " | ".join(problems)[:400])
        init = datetime.strptime(d, "%Y%m%d").replace(tzinfo=timezone.utc)
        for n in days:
            agent = f"Agent_ECMWF_00z_HDD_Day{n}"
            target = (init + timedelta(days=n - 1)).strftime("%Y-%m-%dT00:00:00Z")
            steps = [24 * n - 12, 24 * n - 6, 24 * n, 24 * n + 6]
            if max(steps) > MAX_STEP:
                out.append({"agent": agent, "new": 0, "skipped": f"needs step {max(steps)} > {MAX_STEP} (not in open data)"})
                continue
            if conn.execute("SELECT 1 FROM pit_market_data WHERE agent_id=? AND target_timestamp=?", (agent, target)).fetchone():
                out.append({"agent": agent, "new": 0, "skipped": "already recorded for this run", "init": d})
                continue
            try:
                temps, mods, raw = [], [], b""
                for st in steps:
                    idx, _ = fetch(client, d, st, ".index", sleep=sleep)
                    a, b = parse_index(idx.text)
                    r, url = fetch(client, d, st, ".grib2", headers={"Range": f"bytes={a}-{b}"}, sleep=sleep)
                    raw += r.content
                    mods.append(parsedate_to_datetime(r.headers["last-modified"]) if r.headers.get("last-modified") else now)
                    temps.append(read_metro_temps(r.content))
                    sleep(0.15)                                   # be polite to the open-data hosts
            except (NotPublished, Unavailable) as e:
                out.append({"agent": agent, "new": 0, "error": str(e)[:300], "init": d})
                continue
            value = weighted_hdd([sum(col) / 4 for col in zip(*temps)])
            avail = max(mods).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            h = ingest.archive_payload(conn, raw, "ecmwf_open_data", url.rsplit("-", 3)[0] + f"-{24 * n}h-oper-fc.grib2", 206, retrieved, "application/grib2")
            ok = ingest.record_observation(
                conn, agent_id=agent, target_timestamp=target,
                available_timestamp=avail, value=round(value, 3), source_id="ecmwf_open_data", source_url=url,
                unit="approx. population-weighted HDD (40 metros)", retrieved_timestamp=retrieved, published_timestamp=avail,
                geographic_scope="CONUS approx: 40 metros, population-weighted (not CPC method)", series_id=f"ECMWF_00z_HDD_DAY{n}",
                raw_payload_hash=h, extraction_version="ecmwf_hdd/2", quality_status="validated_approximation", provenance="measured")
            out.append({"agent": agent, "new": int(ok), "hdd": round(value, 2), "init": d})
        conn.commit()
        if out and not any(r.get("new") or r.get("skipped") for r in out) and any(r.get("error") for r in out):
            raise RuntimeError("ECMWF run found but no day could be collected: " + "; ".join(r["error"] for r in out if r.get("error"))[:400])
    finally:
        if own:
            client.close()
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    for r in collect(sqlite3.connect(db)):
        print(r)
