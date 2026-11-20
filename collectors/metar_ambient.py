"""Ambient temperature, dew point and barometric pressure at the airports nearest the US LNG terminals (checklist F5), from the free, keyless
NOAA Aviation Weather Center METAR API (https://aviationweather.gov/api/data/metar).

Used for ONE purpose: a physical ceiling on liquefaction (turbine efficiency falls as the air warms; wet-bulb temperature is the controlling variable).
It is not a demand signal and is never used as a price or demand input (F11/F12). One agent per station and measure:
Agent_AmbientTemp_<ICAO> (degC), Agent_AmbientDew_<ICAO> (degC), Agent_AmbientPress_<ICAO> (hPa, altimeter setting).
Timestamps: target = observation time, published = observation time, available = when THIS process retrieved it (point-in-time)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402,F401
from ingestion.validation.gatekeeper import check  # noqa: E402
from collectors.hh_forward_yahoo import _archive_raw  # noqa: E402

EXTRACTION_VERSION = "metar_ambient_v1"
QUALITY = "official_observation_unrevised"
SOURCE_ID = "noaa_awc_metar"
URL = "https://aviationweather.gov/api/data/metar?ids={ids}&format=json&hours={hours}"
HOURS = 24
# terminal id (markets_engine.GEO_NODES) -> nearest reporting METAR station (checked to report on 2026-11-17)
TERMINAL_STATIONS = {"SAB": "KLCH", "CAM": "KLCH", "CCP": "KLCH", "CRP": "KCRP", "FPT": "KLBX", "PLQ": "KMSY", "ELB": "KSAV", "CVP": "KNHK"}
STATIONS = sorted(set(TERMINAL_STATIONS.values()))
MEASURES = {"temp": ("Agent_AmbientTemp_", "degC"), "dewp": ("Agent_AmbientDew_", "degC"), "altim": ("Agent_AmbientPress_", "hPa")}


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(payload: list) -> list:
    """[(icao, obs_ts, measure, value)] for every complete numeric field; missing fields are skipped, never filled."""
    out = []
    for o in payload or []:
        icao, t = o.get("icaoId"), o.get("obsTime")
        if not icao or not t:
            continue
        for key in MEASURES:
            v = o.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append((icao, iso(t), key, float(v)))
    return out


def collect(conn: sqlite3.Connection | None = None, raw_dir: str | None = None, client=None) -> list:
    own_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(os.environ["DB_PATH"], timeout=30.0)
    rdir = Path(raw_dir) if raw_dir else Path(__file__).resolve().parent.parent / "raw"
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    own_client = client is None
    client = client or httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"})
    url = URL.format(ids=",".join(STATIONS), hours=HOURS)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        sha = _archive_raw(conn, rdir, resp.content, SOURCE_ID, url, resp.status_code, now_ts)
        new = rejected = 0
        for icao, ts, key, value in parse(resp.json()):
            prefix, unit = MEASURES[key]
            agent = prefix + icao
            ok, _why = check(agent, value, unit)
            if not ok:
                rejected += 1
                continue
            if conn.execute("SELECT 1 FROM pit_market_data WHERE agent_id=? AND target_timestamp=? AND published_timestamp=? AND value=?", (agent, ts, ts, value)).fetchone():
                continue
            conn.execute(
                "INSERT INTO pit_market_data (agent_id, target_timestamp, available_timestamp, value, source_id, source_url, retrieved_timestamp, published_timestamp, "
                "revision_timestamp, unit, geographic_scope, series_id, raw_payload_hash, extraction_version, quality_status, provenance) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (agent, ts, now_ts, value, SOURCE_ID, url, now_ts, ts, "", unit, f"METAR {icao}", f"{icao} {key}", sha, EXTRACTION_VERSION, QUALITY, "measured"))
            new += 1
        conn.commit()
        return [{"agent": "Agent_Ambient_*", "stations": STATIONS, "observations_new": new, "rejected_by_gatekeeper": rejected}]
    except Exception as exc:  # noqa: BLE001
        return [{"agent": "Agent_Ambient_*", "observations_new": 0, "error": str(exc)[:160]}]
    finally:
        if own_client:
            client.close()
        if own_conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
