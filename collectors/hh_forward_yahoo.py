"""Collect live delayed NYMEX Henry Hub M1..M12 settlements from Yahoo Finance."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"


def front_12_symbols(ref_date: date | None = None) -> list[tuple[int, str, str]]:
    d = ref_date or datetime.now(timezone.utc).date()
    y, m = d.year, d.month
    out: list[tuple[int, str, str]] = []
    for idx in range(1, 13):
        m += 1
        if m > 12:
            m = 1
            y += 1
        code = _MONTH_CODES[m]
        out.append((idx, f"NG{code}{y % 100:02d}.NYM", f"{y:04d}-{m:02d}"))
    return out


def parse_yahoo_chart(payload: dict[str, Any]) -> tuple[float, str, str]:
    res = payload["chart"]["result"][0]
    meta = res["meta"]
    closes = [c for c in (res.get("indicators", {}).get("quote", [{}])[0].get("close") or []) if c is not None]
    price = meta.get("regularMarketPrice")
    if price is None and closes:
        price = closes[-1]
    if price is None:
        raise ValueError("No close or regularMarketPrice in Yahoo payload")
    ts_epoch = int(meta.get("regularMarketTime") or datetime.now(timezone.utc).timestamp())
    dt = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
    return round(float(price), 4), dt.strftime("%Y-%m-%dT00:00:00Z"), dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _archive_raw(
    conn: sqlite3.Connection,
    raw_dir: Path,
    raw_bytes: bytes,
    source_id: str,
    url: str,
    http_status: int,
    retrieved_ts: str,
) -> str:
    sha = hashlib.sha256(raw_bytes).hexdigest()
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / sha).write_bytes(raw_bytes)
    conn.execute(
        "INSERT OR IGNORE INTO raw_payloads "
        "(raw_payload_hash, source_id, source_url, http_status, retrieved_timestamp, content_type, byte_length, archive_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sha, source_id, url, http_status, retrieved_ts, "application/json", len(raw_bytes), f"raw/{sha}"),
    )
    return sha


def collect(conn: sqlite3.Connection | None = None, raw_dir: str | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(os.environ["DB_PATH"], timeout=30.0)
    root_dir = Path(__file__).resolve().parent.parent
    rdir = Path(raw_dir) if raw_dir else (root_dir / "raw")
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results: list[dict[str, Any]] = []

    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            for idx, sym, delivery_ym in front_12_symbols():
                url = _YAHOO_CHART_URL.format(symbol=sym)
                agent_id = f"Agent_HH_M{idx}"
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    raw_bytes = resp.content
                    price, target_ts, avail_ts = parse_yahoo_chart(resp.json())
                    sha = _archive_raw(conn, rdir, raw_bytes, "yahoo_finance_nymex", url, resp.status_code, now_ts)
                    exists = conn.execute(
                        "SELECT 1 FROM pit_market_data WHERE agent_id=? AND target_timestamp=? AND available_timestamp=?",
                        (agent_id, target_ts, avail_ts),
                    ).fetchone()
                    new_rows = 0
                    if not exists:
                        conn.execute(
                            "INSERT INTO pit_market_data ("
                            "agent_id, target_timestamp, available_timestamp, value, "
                            "source_id, source_url, retrieved_timestamp, published_timestamp, revision_timestamp, "
                            "unit, geographic_scope, series_id, raw_payload_hash, extraction_version, quality_status, provenance"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                agent_id, target_ts, avail_ts, price,
                                "yahoo_finance_nymex", url, now_ts, avail_ts, "",
                                "USD/MMBtu", "Henry Hub, LA (NYMEX)", f"{sym} ({delivery_ym})",
                                sha, "hh_forward_yahoo_v1", "validated_delayed_quote", "measured",
                            ),
                        )
                        new_rows = 1
                    conn.commit()
                    results.append({"agent": agent_id, "symbol": sym, "price": price, "observations_new": new_rows})
                except Exception as exc:
                    results.append({"agent": agent_id, "symbol": sym, "observations_new": 0, "error": str(exc)})
        return results
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
