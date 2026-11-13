"""NOAA GFS 00z forecast HDD (Agent_GFS_00z_HDD_Day1..15) from the keyless NOAA open-data archive on AWS S3.
METHOD (approximation, labelled in geographic_scope): forecast day N covers 06Z of init+N-1 to 06Z of init+N (target = that calendar day); daily mean 2 m
temperature = mean of the four 6-hourly TMP fields f(24N-12), f(24N-6), f(24N), f(24N+6); HDD(F) = max(0, 65 - T_F) computed at ~40 large
CONUS metros and weighted by metro population. This is NOT CPC's regional population-weighted method.
PIT: available_timestamp = S3 Last-Modified of the fetched GRIB (when the run was actually published); forecasts are
recorded as issued and never revised. Only single fields are fetched by byte range (via the .idx), not whole files."""
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
from runtime_paths import scratch_file  # noqa: E402

BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{d}/00/atmos/gfs.t00z.pgrb2.0p25.f{f:03d}"
METROS = [  # (lat, lon, population millions, approximate)
    (40.7, -74.0, 20.1), (34.1, -118.2, 13.2), (41.9, -87.6, 9.6), (32.8, -96.8, 7.6), (29.8, -95.4, 7.1),
    (38.9, -77.0, 6.3), (40.0, -75.2, 6.2), (25.8, -80.2, 6.1), (33.7, -84.4, 6.1), (42.4, -71.1, 4.9),
    (33.4, -112.1, 4.8), (37.8, -122.4, 4.7), (34.0, -117.4, 4.6), (42.3, -83.0, 4.4), (47.6, -122.3, 4.0),
    (44.98, -93.3, 3.7), (32.7, -117.2, 3.3), (27.95, -82.5, 3.2), (39.7, -105.0, 3.0), (38.6, -90.2, 2.8),
    (39.3, -76.6, 2.8), (35.2, -80.8, 2.7), (28.5, -81.4, 2.7), (29.4, -98.5, 2.6), (45.5, -122.7, 2.5),
    (38.6, -121.5, 2.4), (40.4, -80.0, 2.3), (30.3, -97.7, 2.3), (36.2, -115.1, 2.3), (39.1, -84.5, 2.2),
    (39.1, -94.6, 2.2), (40.0, -83.0, 2.1), (39.8, -86.2, 2.1), (41.5, -81.7, 2.1), (36.2, -86.8, 2.0),
    (37.3, -121.9, 2.0), (36.9, -76.0, 1.8), (41.8, -71.4, 1.6), (43.0, -87.9, 1.6), (30.3, -81.7, 1.6)]
TOTAL_POP = sum(m[2] for m in METROS)


def parse_idx(text: str) -> dict:
    """{fhr: (start, end)} for ':TMP:2 m above ground:' byte ranges from a GRIB .idx."""
    lines = [l for l in text.splitlines() if l.strip()]
    out = {}
    for i, l in enumerate(lines):
        p = l.split(":")
        if len(p) > 5 and p[3] == "TMP" and p[4] == "2 m above ground":
            m = re.match(r"(\d+) hour fcst", p[5])
            if m and i + 1 < len(lines):
                out[int(m[1])] = (int(p[1]), int(lines[i + 1].split(":")[1]) - 1)
    return out


def hdd_f(temp_k: float) -> float:
    return max(0.0, 65.0 - ((temp_k - 273.15) * 9 / 5 + 32))


def weighted_hdd(daily_mean_k_by_metro) -> float:
    return sum(hdd_f(t) * m[2] for t, m in zip(daily_mean_k_by_metro, METROS)) / TOTAL_POP


def grid_index(lat: float, lon: float) -> tuple:
    return int(round((90.0 - lat) / 0.25)), int(round((lon % 360) / 0.25)) % 1440


def fetch_range(url: str, start: int, end: int):
    r = httpx.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=90)
    if r.status_code not in (200, 206):
        raise RuntimeError(f"GFS range fetch HTTP {r.status_code}")
    return r.content, r.headers.get("last-modified")


def read_metro_temps(grib_bytes: bytes) -> list:
    import pygrib
    with scratch_file(".grib2", grib_bytes) as grib_path:   # pygrib needs a real file; kept under runtime/scratch/
        g = pygrib.open(grib_path)
        msg = g.message(1)
        vals = msg.values
        if vals.shape != (721, 1440):
            raise ValueError(f"unexpected GFS grid {vals.shape}")
        return [float(vals[grid_index(m[0], m[1])]) for m in METROS]


def latest_run(client, now: datetime):
    for back in (0, 1, 2):
        d = (now - timedelta(days=back)).strftime("%Y%m%d")
        r = client.get(BASE.format(d=d, f=24) + ".idx", timeout=30)
        if r.status_code == 200:
            return d
    raise RuntimeError("no GFS 00z run found in last 3 days")


def collect(conn, now: datetime = None, days=range(1, 16)) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    with httpx.Client() as client:
        d = latest_run(client, now)
        init = datetime.strptime(d, "%Y%m%d").replace(tzinfo=timezone.utc)
        for n in days:
            agent = f"Agent_GFS_00z_HDD_Day{n}"
            fhrs = [24 * n - 12, 24 * n - 6, 24 * n, 24 * n + 6]  # 06Z..06Z window ~ US central calendar day
            temps, lastmod, raw = [], [], b""
            for f in fhrs:
                url = BASE.format(d=d, f=f)
                rng = parse_idx(client.get(url + ".idx", timeout=30).text).get(f)
                if not rng:
                    raise ValueError(f"TMP 2m f{f:03d} not in idx")
                body, lm = fetch_range(url, *rng)
                raw += body
                lastmod.append(parsedate_to_datetime(lm) if lm else now)
                temps.append(read_metro_temps(body))
            daily_mean = [sum(col) / 4 for col in zip(*temps)]
            value = weighted_hdd(daily_mean)
            avail = max(lastmod).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            h = ingest.archive_payload(conn, raw, "noaa_gfs_open_data", BASE.format(d=d, f=24 * n), 206, retrieved, "application/grib2")
            ok = ingest.record_observation(
                conn, agent_id=agent, target_timestamp=(init + timedelta(days=n - 1)).strftime("%Y-%m-%dT00:00:00Z"),
                available_timestamp=avail, value=round(value, 3), source_id="noaa_gfs_open_data",
                source_url=BASE.format(d=d, f=24 * n), unit="approx. population-weighted HDD (40 metros)", retrieved_timestamp=retrieved,
                published_timestamp=avail, geographic_scope="CONUS approx: 40 metros, population-weighted (not CPC method)",
                series_id=f"GFS_00z_HDD_DAY{n}", raw_payload_hash=h, extraction_version="gfs_hdd/1",
                quality_status="validated_approximation", provenance="measured")
            out.append({"agent": agent, "new": int(ok), "hdd": round(value, 2), "init": d})
        conn.commit()
    return out


if __name__ == "__main__":
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    for r in collect(sqlite3.connect(db)):
        print(r)

# CALIBRATION (30 days, Day-1 forecast vs NOAA CPC observed HDD): corr ~0.59, bias ~ -4 HDD (proxy runs low: 40 metros, not
# CPC's full population weighting). Treat as a RELATIVE signal and calibrate PIT-safely (rolling) before using levels.
