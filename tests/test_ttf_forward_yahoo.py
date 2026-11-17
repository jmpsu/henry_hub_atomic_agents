import json, sqlite3, sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import init_db  # noqa: E402
from collectors import hh_forward_yahoo as hf  # noqa: E402
from collectors import ttf_forward_yahoo as tf  # noqa: E402


def _payload(price, qtime):
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "regularMarketTime": qtime}, "indicators": {"quote": [{"close": [price]}]}}]}}


def _client(routes):
    """routes: substring of the URL -> (status, price, quote_time); anything else 404 (the way Yahoo answers for an unlisted contract)."""
    def handler(request):
        for key, (code, price, qt) in routes.items():
            if key in str(request.url):
                return httpx.Response(code, content=json.dumps(_payload(price, qt)).encode())
        return httpx.Response(404, content=b"{}")
    return httpx.Client(transport=httpx.MockTransport(handler))


def _conn():
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    return sqlite3.connect(db)


def test_symbols_and_agents_align_with_the_henry_hub_delivery_months():
    assert tf.ttf_symbol("2026-12") == "TTFZ26.NYM" and tf.ttf_symbol("2027-01") == "TTFF27.NYM"
    assert tf.agent_for("2026-12") == "Agent_TTF_2026_12"
    hh_months = [ym for _i, _s, ym in hf.front_12_symbols(date(2026, 11, 17))]
    assert hh_months[0] == "2026-12" and len(hh_months) == 12 and len({tf.agent_for(m) for m in hh_months}) == 12


def test_collect_stores_pit_safe_rows_reports_unlisted_months_and_never_invents_a_value():
    conn = _conn()
    q = 1794901761                                                    # Yahoo's own quote time (past)
    first = hf.front_12_symbols()[0][2]
    c = _client({tf.ttf_symbol(first): (200, 84.38, q), "EURUSD": (200, 1.0996, q)})
    res = tf.collect(conn, raw_dir=_scratch.mkdtemp(), client=c)
    ok = [r for r in res if r["observations_new"] == 1]
    assert {r["agent"] for r in ok} == {tf.agent_for(first), "Agent_FX_EURUSD"}
    assert sum(1 for r in res if r.get("error")) == 11                # the other 11 TTF months: unlisted -> an error entry, no row
    rows = conn.execute("SELECT agent_id, value, unit, available_timestamp, published_timestamp, retrieved_timestamp, quality_status, extraction_version, series_id FROM pit_market_data").fetchall()
    assert len(rows) == 2
    for agent, val, unit, avail, pub, retr, qs, ver, sid in rows:
        assert avail == retr and avail > pub and qs == "delayed_quote_unverified" and ver == tf.EXTRACTION_VERSION    # available = OUR retrieval time, after Yahoo's quote time
    d = {r[0]: r for r in rows}
    assert d["Agent_FX_EURUSD"][1] == 1.0996 and d["Agent_FX_EURUSD"][2] == "USD/EUR" and d[tf.agent_for(first)][2] == "EUR/MWh" and "TTF" in d[tf.agent_for(first)][8]


def test_same_quote_is_not_stored_twice_but_a_new_quote_is(monkeypatch):
    conn = _conn()
    first = hf.front_12_symbols()[0][2]
    q = 1794901761
    tf.collect(conn, raw_dir=_scratch.mkdtemp(), client=_client({tf.ttf_symbol(first): (200, 84.38, q)}))
    r2 = tf.collect(conn, raw_dir=_scratch.mkdtemp(), client=_client({tf.ttf_symbol(first): (200, 84.38, q)}))
    assert [x["observations_new"] for x in r2 if x["agent"] == tf.agent_for(first)] == [0]
    import time
    time.sleep(1.1)                                                    # PK is (agent, target, available) at 1 s resolution
    r3 = tf.collect(conn, raw_dir=_scratch.mkdtemp(), client=_client({tf.ttf_symbol(first): (200, 85.0, q + 600)}))
    assert [x["observations_new"] for x in r3 if x["agent"] == tf.agent_for(first)] == [1]


def test_gatekeeper_rejects_implausible_values():
    conn = _conn()
    first = hf.front_12_symbols()[0][2]
    res = tf.collect(conn, raw_dir=_scratch.mkdtemp(), client=_client({tf.ttf_symbol(first): (200, 99999.0, 1794901761), "EURUSD": (200, 12.0, 1794901761)}))
    bad = [r for r in res if r.get("error") and ("gatekeeper" in r["error"])]
    assert len(bad) == 2 and conn.execute("SELECT COUNT(*) FROM pit_market_data").fetchone()[0] == 0
