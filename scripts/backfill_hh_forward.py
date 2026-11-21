#!/usr/bin/env python3
"""Backfill historical daily-close M1..M12 curves for Henry Hub from Yahoo (NG<month><yy>.NYM), additively and idempotently.

Only trade dates for which ALL 12 contracts (mapped by the expiry-aware roll in collectors.hh_forward_yahoo.front_12_symbols) have a
close are written; expired contracts are not served by Yahoo, so older dates are skipped rather than filled with a shifted or partial curve.
PIT semantics: available_timestamp = the time this script retrieved the bar (never the trade date), so any historical as_of earlier than
the backfill cannot see these rows. Existing (agent, target) rows are never touched. Dry run is the default; --apply backs the DB up first.

  python scripts/backfill_hh_forward.py                 # dry run: fetch, plan, print; writes nothing
  python scripts/backfill_hh_forward.py --apply         # backup then insert
Rollback: DELETE FROM pit_market_data WHERE extraction_version='hh_forward_backfill_v1';  (or restore the printed backup file)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collectors import hh_forward_yahoo as hf  # noqa: E402

VERSION = "hh_forward_backfill_v1"
QUALITY = "historical_daily_close_unverified"
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"


def plan(closes: dict[str, dict[str, float]], dates: list[date]) -> tuple[list[dict], list[dict]]:
    """closes[symbol][YYYY-MM-DD] -> close. Returns (rows, skipped). A date is complete only if all 12 mapped contracts have a close."""
    rows, skipped = [], []
    for d in dates:
        syms = hf.front_12_symbols(d)
        got = [(i, s, ym, closes.get(s, {}).get(d.isoformat())) for i, s, ym in syms]
        missing = [s for _, s, _, c in got if c is None]
        if missing:
            skipped.append({"date": d.isoformat(), "missing": missing})
            continue
        rows += [{"agent": f"Agent_HH_M{i}", "target": f"{d.isoformat()}T00:00:00Z", "value": c, "symbol": s, "month": ym} for i, s, ym, c in got]
    return rows, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("DB_PATH") or str(ROOT / "henry_hub_pit.db"))
    ap.add_argument("--range", default="6mo", dest="rng")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    now_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now.date()                     # today's bar is in progress and is covered by the live collector
    start = today - timedelta(days=185 if a.rng == "6mo" else 95)
    dates = [start + timedelta(days=i) for i in range((today - start).days) if (start + timedelta(days=i)).weekday() < 5]
    need = sorted({s for d in dates for _, s, _ in hf.front_12_symbols(d)})

    closes, payloads, errors = {}, {}, {}
    with httpx.Client(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}) as cl:
        for sym in need:
            url = URL.format(symbol=sym, rng=a.rng)
            try:
                r = cl.get(url)
                r.raise_for_status()
                closes[sym] = dict(hf.parse_daily_closes(r.json()))
                payloads[sym] = (url, r.content, r.status_code)
            except Exception as e:  # noqa: BLE001  expired/delisted symbols land here and make their dates incomplete
                errors[sym] = str(e)[:80]
            time.sleep(0.2)

    ro = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    have = {(r[0], r[1]) for r in ro.execute("SELECT agent_id, target_timestamp FROM pit_market_data WHERE agent_id GLOB 'Agent_HH_M[0-9]*'")}
    ro.close()
    rows, skipped = plan(closes, dates)
    new = [r for r in rows if (r["agent"], r["target"]) not in have]
    summary = {"db": a.db, "mode": "APPLY" if a.apply else "DRY-RUN", "symbols_fetched": len(closes), "symbols_unavailable": errors,
               "complete_dates": sorted({r["target"][:10] for r in rows}), "rows_planned": len(rows), "rows_already_present": len(rows) - len(new),
               "rows_to_insert": len(new), "dates_skipped_incomplete": len(skipped)}
    if not a.apply:
        print(json.dumps(summary, indent=1))
        return 0

    backup = f"{a.db}.pre-fwd-backfill.{now.strftime('%Y%m%dT%H%M%SZ')}"
    src, dst = sqlite3.connect(a.db), sqlite3.connect(backup)
    src.backup(dst)
    dst.close()
    conn = src
    raw = ROOT / "raw"
    raw.mkdir(exist_ok=True)
    hashes = {}
    for sym, (url, content, status) in payloads.items():
        sha = hashlib.sha256(content).hexdigest()
        (raw / sha).write_bytes(content)
        conn.execute("INSERT OR IGNORE INTO raw_payloads (raw_payload_hash, source_id, source_url, http_status, retrieved_timestamp, content_type, byte_length, archive_path) "
                     "VALUES (?,?,?,?,?,?,?,?)", (sha, "yahoo_finance_nymex", url, status, now_ts, "application/json", len(content), f"raw/{sha}"))
        hashes[sym] = sha
    for r in new:
        conn.execute("INSERT INTO pit_market_data (agent_id,target_timestamp,available_timestamp,value,source_id,source_url,retrieved_timestamp,published_timestamp,"
                     "revision_timestamp,unit,geographic_scope,series_id,raw_payload_hash,extraction_version,quality_status,provenance) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (r["agent"], r["target"], now_ts, r["value"], "yahoo_finance_nymex", payloads[r["symbol"]][0], now_ts, "", "", "USD/MMBtu",
                      "Henry Hub, LA (NYMEX)", f"{r['symbol']} ({r['month']})", hashes[r["symbol"]], VERSION, QUALITY, "measured"))
    conn.commit()
    conn.close()
    print(json.dumps({**summary, "backup": backup, "inserted": len(new)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
