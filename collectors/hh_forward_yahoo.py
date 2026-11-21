"""Collect live delayed NYMEX Henry Hub M1..M12 quotes from Yahoo Finance (NG<month><yy>.NYM).

These are delayed, unofficial quotes (regularMarketPrice), NOT exchange settlements, and are labelled `delayed_quote_unverified`.
Timestamps: target = quote date; published = Yahoo regularMarketTime; available = when THIS process retrieved it (never earlier).
Contract roll: M1 is the first contract whose last-trade date (3 business days before the first calendar day of the delivery month)
is on or after the trade date, so the expired prompt month is never requested and no label shifts by one.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

EXTRACTION_VERSION = "hh_forward_yahoo_v4"
QUALITY = "delayed_quote_unverified"
_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"


def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    j, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7
    mo = (h - m + r + 90) // 25
    return date(y, mo, (h - m + r + mo + 19) % 32)


def _nth_weekday(y: int, m: int, wd: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(wd - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _holidays(y: int) -> set[date]:
    """Approximate NYMEX full-closure days: fixed-date holidays (Sunday -> Monday), MLK, Presidents, Good Friday, Memorial, Thanksgiving."""
    fixed = []
    for m, dd in ((1, 1), (6, 19), (7, 4), (12, 25)):
        d = date(y, m, dd)
        fixed.append(d + timedelta(days=1) if d.weekday() == 6 else d)
    last_mon_may = max(d for d in (date(y, 5, x) for x in range(25, 32)) if d.weekday() == 0)
    return {*fixed, _nth_weekday(y, 1, 0, 3), _nth_weekday(y, 2, 0, 3), _easter(y) - timedelta(days=2), last_mon_may,
            _nth_weekday(y, 9, 0, 1), _nth_weekday(y, 11, 3, 4)}


def _is_bday(d: date) -> bool:
    return d.weekday() < 5 and d not in _holidays(d.year)


def contract_expiry(y: int, m: int) -> date:
    """Last trade date of the NG contract delivering in month (y, m): 3 business days before the 1st of the delivery month."""
    d, n = date(y, m, 1), 0
    while n < 3:
        d -= timedelta(days=1)
        n += _is_bday(d)
    return d


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y, m + 1) if m < 12 else (y + 1, 1)


def front_12_symbols(ref_date: date | None = None) -> list[tuple[int, str, str]]:
    """[(M-index, Yahoo symbol, delivery YYYY-MM)] for trade date `ref_date`. A contract delivering in month X last trades in month X-1,
    so for a trade date in month m the earliest candidate is m+1, and it is M1 only if it has not yet expired (ref_date <= expiry)."""
    d = ref_date or datetime.now(timezone.utc).date()
    y, m = _next_month(d.year, d.month)
    if d > contract_expiry(y, m):
        y, m = _next_month(y, m)
    out: list[tuple[int, str, str]] = []
    for idx in range(1, 13):
        out.append((idx, f"NG{_MONTH_CODES[m]}{y % 100:02d}.NYM", f"{y:04d}-{m:02d}"))
        y, m = _next_month(y, m)
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


def parse_daily_closes(payload: dict[str, Any]) -> list[tuple[str, float]]:
    """[(exchange-local trade date YYYY-MM-DD, close)] from a range=Nmo&interval=1d chart payload; null closes are skipped."""
    res = payload["chart"]["result"][0]
    off = int(res["meta"].get("gmtoffset") or 0)
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    out = []
    for ts, c in zip(res.get("timestamp") or [], closes):
        if c is not None:
            out.append((datetime.fromtimestamp(int(ts) + off, tz=timezone.utc).strftime("%Y-%m-%d"), round(float(c), 4)))
    return out


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
                    price, target_ts, published_ts = parse_yahoo_chart(resp.json())
                    sha = _archive_raw(conn, rdir, raw_bytes, "yahoo_finance_nymex", url, resp.status_code, now_ts)
                    # a new vintage only when Yahoo's quote actually changed (same quote time and price = same observation)
                    exists = conn.execute(
                        "SELECT 1 FROM pit_market_data WHERE agent_id=? AND target_timestamp=? AND published_timestamp=? AND value=?",
                        (agent_id, target_ts, published_ts, price),
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
                                agent_id, target_ts, now_ts, price,
                                "yahoo_finance_nymex", url, now_ts, published_ts, "",
                                "USD/MMBtu", "Henry Hub, LA (NYMEX)", f"{sym} ({delivery_ym})",
                                sha, EXTRACTION_VERSION, QUALITY, "measured",
                            ),
                        )
                        new_rows = 1
                    conn.commit()
                    results.append({"agent": agent_id, "symbol": sym, "contract_month": delivery_ym, "target_timestamp": target_ts,
                                    "available_timestamp": now_ts, "published_timestamp": published_ts, "price": price,
                                    "quality_status": QUALITY, "observations_new": new_rows})
                except Exception as exc:
                    results.append({"agent": agent_id, "symbol": sym, "contract_month": delivery_ym, "observations_new": 0, "error": str(exc)})
        return results
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
