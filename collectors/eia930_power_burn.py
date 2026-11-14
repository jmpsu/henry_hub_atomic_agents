"""US48 gas-fired power generation from the EIA Hourly Electric Grid Monitor (EIA-930) six-month bulk files (keyless CSV):
https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_<YYYY>_<Jan_Jun|Jul_Dec>.csv
Agent_Demand_PowerBurn <- sum over all balancing authorities of hourly "Net Generation (MW) from Natural Gas (Adjusted)"
(EIA's cleaned series; the raw column is used for an hour only if the adjusted one is blank), per UTC day, in MWh/day.
The roster's MWh/Bcf ratio would need a heat-rate assumption, so only measured generation is stored.
A UTC day is stored only when complete (>=97% of balancing-authority hours present) and at least one day older than the
newest data in the file. PIT assumption (documented): day D is public by D+2 12:00Z. EIA revises these data; a changed day
is stored as a new vintage available at retrieval time."""
import csv
import io
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402

URL = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{year}_{half}.csv"
AGENT = "Agent_Demand_PowerBurn"
COL_ADJ, COL_RAW = "Net Generation (MW) from Natural Gas (Adjusted)", "Net Generation (MW) from Natural Gas"


def fetch(url):
    r = httpx.get(url, timeout=300, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    return r.status_code, r.content, r.headers.get("content-type", "")


def url_for(d: datetime) -> str:
    return URL.format(year=d.year, half="Jan_Jun" if d.month <= 6 else "Jul_Dec")


def num(x: str):
    x = (x or "").replace(",", "").strip()
    try:
        return float(x)
    except ValueError:
        return None


def partials(body: bytes):
    """Per-UTC-day partial sums from one file: (mwh, ba_hours, bas, newest_day)."""
    rd = csv.reader(io.StringIO(body.decode("utf-8", "ignore")))
    h = next(rd)
    try:
        ba_i, utc_i, adj_i, raw_i = h.index("Balancing Authority"), h.index("UTC Time at End of Hour"), h.index(COL_ADJ), h.index(COL_RAW)
    except ValueError as e:
        raise ValueError(f"unexpected EIA-930 header: {e}")
    mwh, hours, bas = defaultdict(float), defaultdict(int), defaultdict(set)
    newest = None
    for row in rd:
        if len(row) <= max(ba_i, utc_i, adj_i, raw_i):
            continue
        try:
            end = datetime.strptime(row[utc_i].strip(), "%m/%d/%Y %I:%M:%S %p")
        except ValueError:
            continue
        day = (end - timedelta(hours=1)).strftime("%Y-%m-%d")          # hour-ending -> the hour belongs to the day it started in
        newest = max(newest or day, day)
        bas[day].add(row[ba_i])
        hours[day] += 1                                                 # completeness = reported BA-hours (rows)
        v = num(row[adj_i])
        v = num(row[raw_i]) if v is None else v
        if v is not None:                                               # blank = that BA reported no gas generation that hour
            mwh[day] += max(v, 0.0)
    if not newest:
        raise ValueError("no hourly rows parsed")
    return mwh, hours, bas, newest


def finalize(parts) -> dict:
    """Merge partial sums from one or more files (half-year files split the boundary days) and keep complete days only."""
    mwh, hours, bas, newest = defaultdict(float), defaultdict(int), defaultdict(set), None
    for m_, h_, b_, n_ in parts:
        for d, v in m_.items():
            mwh[d] += v
        for d, v in h_.items():
            hours[d] += v
        for d, v in b_.items():
            bas[d] |= v
        newest = max(newest or n_, n_)
    cutoff = (datetime.strptime(newest, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    # complete = every balancing authority reporting that day has (nearly) all 24 hours; EIA lists a row for every
    # reporting BA even when its values are blank, and the BA set changes over the years, so it is judged per day
    return {d: round(mwh[d], 1) for d in sorted(hours) if d < cutoff and hours[d] >= 0.97 * 24 * len(bas[d])}


def parse(body: bytes) -> dict:
    """{YYYY-MM-DD: MWh} for complete UTC days in a single file."""
    return finalize([partials(body)])


def collect(conn, fetcher=fetch, now=None, urls=None) -> list:
    now = now or datetime.now(timezone.utc)
    retrieved = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    urls = urls or sorted({url_for(now - timedelta(days=3)), url_for(now)})   # the half-year boundary needs both files for a few days
    known = {r[1][:10]: r[3] for r in ingest.pit_snapshot(conn, "2100-01-01T00:00:00Z", [AGENT], measured_only=False)}
    parts, src = [], {}
    for url in urls:
        status, body, ctype = fetcher(url)
        if status == 404:
            continue                                                       # next half-year file does not exist yet
        if status != 200:
            raise RuntimeError(f"EIA-930 HTTP {status}")
        h = ingest.archive_payload(conn, body, "eia930_balance", url, status, retrieved, ctype)
        p = partials(body)
        parts.append(p)
        for d in p[1]:
            src[d] = (url, h)                                              # payload that contributed the day (last one wins)
    new = 0
    for day, v in (finalize(parts).items() if parts else []):
        prev = known.get(day)
        if prev is not None and abs(prev - v) < 0.5:                       # sub-MWh float noise is not a revision
            continue
        revised = prev is not None
        avail = retrieved if revised else (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=2, hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not revised and avail > retrieved:
            continue
        url, h = src[day]
        new += int(ingest.record_observation(
            conn, agent_id=AGENT, target_timestamp=day + "T00:00:00Z", available_timestamp=avail, value=v, source_id="eia930_balance",
            source_url=url, unit="MWh/day (US48 gas-fired net generation)", retrieved_timestamp=retrieved,
            revision_timestamp=retrieved if revised else None, geographic_scope="US48 (EIA-930 balancing authorities)",
            series_id="EIA930.NG.adjusted.sum", raw_payload_hash=h, extraction_version="eia930_power_burn/1",
            quality_status="revision_vintage" if revised else "validated_availability_assumed_d+2", provenance="measured"))
    conn.commit()
    return [{"agent": AGENT, "observations_new": new}]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-from", type=int, help="also load every half-year file from this year on")
    a = ap.parse_args()
    db = os.environ.get("DB_PATH") or str(Path(__file__).resolve().parent.parent / "henry_hub_pit.db")
    urls = None
    if a.backfill_from:
        now = datetime.now(timezone.utc)
        urls = [URL.format(year=y, half=h) for y in range(a.backfill_from, now.year + 1) for h in ("Jan_Jun", "Jul_Dec")
                if not (y == now.year and h == "Jul_Dec" and now.month <= 6)]
    print(collect(sqlite3.connect(db), urls=urls))
