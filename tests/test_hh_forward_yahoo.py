from datetime import date
from collectors.hh_forward_yahoo import front_12_symbols, parse_yahoo_chart


def test_front_12_symbols():
    syms = front_12_symbols(date(2026, 11, 15))
    assert len(syms) == 12
    assert syms[0] == (1, "NGZ26.NYM", "2026-12")
    assert syms[1] == (2, "NGF27.NYM", "2027-01")
    assert syms[-1] == (12, "NGX27.NYM", "2027-11")


def test_parse_yahoo_chart():
    sample = {
        "chart": {
            "result": [{
                "meta": {"regularMarketPrice": 3.456, "regularMarketTime": 1794749400},
                "indicators": {"quote": [{"close": [3.41, 3.456]}]},
            }]
        }
    }
    price, target_ts, avail_ts = parse_yahoo_chart(sample)
    assert price == 3.456
    assert target_ts.endswith("T00:00:00Z")
    assert avail_ts.endswith("Z")


# ---- v4: expiry-aware roll, PIT timestamps, honest quality, vintage dedup, engine metadata passthrough -------------------------------
import json
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _scratch  # noqa: E402
import init_db  # noqa: E402
import ingest  # noqa: E402
import markets_engine as me  # noqa: E402
from collectors import hh_forward_yahoo as hf  # noqa: E402


def test_contract_expiry_known_dates():
    assert hf.contract_expiry(2026, 11) == date(2026, 10, 28)   # NGX26: 3 business days before Nov 1 (Sun) -> Wed Oct 28; matches Yahoo "delisted" for NGX26
    assert hf.contract_expiry(2026, 12) == date(2026, 11, 25)   # Thanksgiving (Nov 26) is skipped as a non-business day
    assert hf.contract_expiry(2027, 1) == date(2026, 12, 29)


def test_roll_does_not_request_expired_contract():
    assert hf.front_12_symbols(date(2026, 10, 28))[0][1:] == ("NGX26.NYM", "2026-11")     # expiry day: still M1
    m = hf.front_12_symbols(date(2026, 10, 29))
    assert m[0][1:] == ("NGZ26.NYM", "2026-12") and m[-1][1:] == ("NGX27.NYM", "2027-11")  # day after: rolled, labels not shifted
    assert hf.front_12_symbols(date(2026, 11, 25))[0][2] == "2026-12"
    assert hf.front_12_symbols(date(2026, 11, 26))[0][2] == "2027-01"
    assert [x[2] for x in hf.front_12_symbols(date(2026, 12, 31))][:2] == ["2027-02", "2027-03"]
    assert len({x[1] for x in hf.front_12_symbols(date(2026, 12, 15))}) == 12


def test_parse_daily_closes_uses_exchange_date_and_skips_nulls():
    p = {"chart": {"result": [{"meta": {"gmtoffset": -18000}, "timestamp": [1794816000, 1794902400, 1794988800],   # 04:00Z = 23:00 prior ET? use offset
                               "indicators": {"quote": [{"close": [3.1, None, 3.3]}]}}]}}
    out = hf.parse_daily_closes(p)
    assert [c for _, c in out] == [3.1, 3.3] and all(len(d) == 10 for d, _ in out)


def _payload(price, qtime):
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "regularMarketTime": qtime},
                                  "indicators": {"quote": [{"close": [price]}]}}]}}


def _run_collect(db, qtime, price):
    def handler(request):
        return httpx.Response(200, content=json.dumps(_payload(price, qtime)).encode(), headers={"content-type": "application/json"})
    real = httpx.Client
    hf.httpx.Client = lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    try:
        conn = sqlite3.connect(db)
        res = hf.collect(conn, raw_dir=_scratch.mkdtemp())
        conn.close()
        return res
    finally:
        hf.httpx.Client = real


def _db():
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)          # the project's own schema creator (same one tests/test_markets_engine.py uses)
    return db


def test_collect_writes_pit_safe_labelled_rows_and_dedups():
    db = _db()
    q = 1794901761                                           # Yahoo's own quote time, in the past
    r1 = _run_collect(db, q, 3.2)
    assert len(r1) == 12 and all(x["observations_new"] == 1 for x in r1) and r1[0]["contract_month"]
    c = sqlite3.connect(db)
    rows = c.execute("SELECT agent_id, available_timestamp, published_timestamp, retrieved_timestamp, quality_status, extraction_version, series_id "
                     "FROM pit_market_data").fetchall()
    assert len(rows) == 12
    for agent, avail, pub, retr, qs, ver, sid in rows:
        assert avail == retr and avail > pub                 # available = OUR retrieval time, strictly after Yahoo's quote time (no look-ahead)
        assert qs == "delayed_quote_unverified" and ver == hf.EXTRACTION_VERSION and "(" in sid
    assert _run_collect(db, q, 3.2)[0]["observations_new"] == 0          # same quote again -> no duplicate vintage
    import time
    time.sleep(1.1)                                          # PK is (agent, target, available) at 1 s resolution; real runs are minutes apart
    r3 = _run_collect(db, q + 600, 3.25)
    assert r3[0]["observations_new"] == 1, r3[0]             # changed quote -> new vintage
    c.close()
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM pit_market_data WHERE agent_id='Agent_HH_M1'").fetchone()[0] == 2
    c.close()


def test_engine_forward_points_carry_lineage_metadata():
    db = _db()
    _run_collect(db, 1794901761, 3.2)
    st = me.build_state(db, as_of="2099-01-01T00:00:00Z")
    pts = st["curves"]["forward_curve"]["points"]
    assert len(pts) == 12
    p = pts[4]
    assert p["contract"] == "M5" and p["delivery_month"] and p["series_id"].startswith("NG") and p["source_id"] == "yahoo_finance_nymex"
    assert p["quality_status"] == "delayed_quote_unverified" and p["published_timestamp"] and p["raw_payload_hash"]
    assert p["available_timestamp"] > p["published_timestamp"]


def test_backfill_plan_only_emits_complete_curves_and_never_shifts_labels():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import backfill_hh_forward as bf
    d_ok, d_gap = date(2026, 11, 3), date(2026, 10, 27)          # Nov 3: M1=Dec26 ; Oct 27: M1=Nov26 (NGX26, not served by Yahoo)
    closes = {s: {d_ok.isoformat(): 3.0 + i / 100} for i, s, _ in hf.front_12_symbols(d_ok)}
    for _, s, _ in hf.front_12_symbols(d_gap):
        closes.setdefault(s, {})[d_gap.isoformat()] = 9.99
    closes.pop("NGX26.NYM", None)                                # expired contract unavailable
    rows, skipped = bf.plan(closes, [d_gap, d_ok])
    assert [r["target"][:10] for r in rows] == [d_ok.isoformat()] * 12
    assert rows[0]["agent"] == "Agent_HH_M1" and rows[0]["symbol"] == "NGZ26.NYM" and rows[11]["symbol"] == "NGX27.NYM"
    assert skipped == [{"date": d_gap.isoformat(), "missing": ["NGX26.NYM"]}]
