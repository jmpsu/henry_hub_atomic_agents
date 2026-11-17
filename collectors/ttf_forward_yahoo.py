"""Collect delayed ICE/NYMEX Dutch TTF monthly futures (TTF<month><yy>.NYM, EUR/MWh) and the EUR/USD rate (EURUSD=X) from Yahoo Finance.

Used only for the TTF netback in the LNG forward panel (lng_forward.py). One agent per DELIVERY MONTH (Agent_TTF_<yyyy>_<mm>) so each month aligns with the
Henry Hub contract for the same delivery month; the 12 months collected are the same delivery months as hh_forward_yahoo's M1..M12.
Quotes are delayed and unofficial (quality `delayed_quote_unverified`). Timestamps: target = quote date, published = Yahoo regularMarketTime,
available = when THIS process retrieved it. A deferred month may not have traded for days: the last price is stored as it is with its true published time and the
consumer (lng_forward) refuses to use a quote older than lng_config.MAX_QUOTE_AGE_DAYS. JKM has no free futures source (Yahoo JKM=F has no data) and is not collected."""
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
from collectors.hh_forward_yahoo import _MONTH_CODES, _YAHOO_CHART_URL, _archive_raw, front_12_symbols, parse_yahoo_chart  # noqa: E402

EXTRACTION_VERSION = "ttf_forward_yahoo_v1"
QUALITY = "delayed_quote_unverified"
FX_AGENT = "Agent_FX_EURUSD"
FX_SYMBOL = "EURUSD=X"


def agent_for(delivery_ym: str) -> str:
    return "Agent_TTF_" + delivery_ym.replace("-", "_")


def ttf_symbol(delivery_ym: str) -> str:
    y, m = int(delivery_ym[:4]), int(delivery_ym[5:7])
    return f"TTF{_MONTH_CODES[m]}{y % 100:02d}.NYM"


def _store(conn, client, rdir, now_ts, agent_id, symbol, label, unit, geo) -> dict:
    url = _YAHOO_CHART_URL.format(symbol=symbol)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        price, target_ts, published_ts = parse_yahoo_chart(resp.json())
        ok, why = check(agent_id, float(price), unit)                   # the project's deterministic physical-range gate (ingest.record_observation applies it; raw INSERTs must too)
        if not ok:
            raise ValueError(f"gatekeeper rejected {agent_id}: {why}")
        sha = _archive_raw(conn, rdir, resp.content, "yahoo_finance_nymex", url, resp.status_code, now_ts)
        if conn.execute("SELECT 1 FROM pit_market_data WHERE agent_id=? AND target_timestamp=? AND published_timestamp=? AND value=?",
                        (agent_id, target_ts, published_ts, price)).fetchone():
            new = 0
        else:
            conn.execute(
                "INSERT INTO pit_market_data (agent_id, target_timestamp, available_timestamp, value, source_id, source_url, retrieved_timestamp, published_timestamp, "
                "revision_timestamp, unit, geographic_scope, series_id, raw_payload_hash, extraction_version, quality_status, provenance) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (agent_id, target_ts, now_ts, price, "yahoo_finance_nymex", url, now_ts, published_ts, "", unit, geo, label, sha, EXTRACTION_VERSION, QUALITY, "measured"))
            new = 1
        conn.commit()
        return {"agent": agent_id, "symbol": symbol, "price": price, "published_timestamp": published_ts, "target_timestamp": target_ts, "observations_new": new}
    except Exception as exc:  # noqa: BLE001  a month Yahoo does not list (404) or a rejected value is reported, never replaced by a guess
        return {"agent": agent_id, "symbol": symbol, "observations_new": 0, "error": str(exc)[:160]}


def collect(conn: sqlite3.Connection | None = None, raw_dir: str | None = None, client=None) -> list:
    own_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(os.environ["DB_PATH"], timeout=30.0)
    rdir = Path(raw_dir) if raw_dir else Path(__file__).resolve().parent.parent / "raw"
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    own_client = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"})
    results = []
    try:
        for _idx, _ng, ym in front_12_symbols():
            sym = ttf_symbol(ym)
            r = _store(conn, client, rdir, now_ts, agent_for(ym), sym, f"{sym} ({ym})", "EUR/MWh", "Netherlands TTF (ICE Endex via NYMEX listing)")
            results.append({**r, "contract_month": ym})
        results.append({**_store(conn, client, rdir, now_ts, FX_AGENT, FX_SYMBOL, FX_SYMBOL, "USD/EUR", "EUR/USD spot"), "contract_month": None})
        return results
    finally:
        if own_client:
            client.close()
        if own_conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
