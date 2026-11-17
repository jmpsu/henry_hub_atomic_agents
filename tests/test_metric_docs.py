"""Every figure on the dashboard has a definition served by the API, parameters cannot drift from the code, and the UI only references real ids."""
import inspect
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import init_db  # noqa: E402
import ingest  # noqa: E402
import markets_engine as me  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_every_doc_has_title_and_what_and_no_market_values():
    docs = me.explain()
    assert len(docs) >= 40
    for k, d in docs.items():
        assert d["title"] and d["what"], k
        assert set(d) == {"title", "what", "formula", "params", "read", "caveat"}, k


def test_parameters_in_docs_equal_the_code_defaults():
    d = me.explain()
    assert d["rsi14"]["params"]["period"] == inspect.signature(me.rsi).parameters["period"].default == 14
    assert d["macd"]["params"] == {"fast": 12, "slow": 26, "signal": 9} and "EMA12" in d["macd"]["formula"]
    assert d["bandwidth"]["params"]["window"] == inspect.signature(me.bollinger).parameters["window"].default
    assert d["squeeze"]["params"]["percentile"] == inspect.signature(me.bollinger).parameters["squeeze_pct"].default
    assert d["triangle"]["params"]["lookback"] == inspect.signature(me.triangle_detection).parameters["lookback"].default
    assert d["pct_of_wti"]["params"]["gallons_per_barrel"] == me.GAL_PER_BBL and "42" in d["pct_of_wti"]["formula"]
    assert d["frac_spread"]["params"]["mmbtu_per_gallon_ethane"] == me.ETHANE_MMBTU_PER_GAL and "0.0665" in d["frac_spread"]["formula"]
    assert all(f"{r * 100:.1f}%" in d["fib_level"]["what"] for r in me.FIB_RATIOS)
    assert str(inspect.signature(me.curve_regime).parameters["flat_band"].default) in d["regime"]["what"]


def test_ui_references_only_ids_that_exist_and_every_doc_is_used():
    docs = me.explain()
    js = (ROOT / "web" / "app.js").read_text() + (ROOT / "web" / "knowledge.js").read_text()
    called = set(re.findall(r'\b(?:X|spec|T)\("([a-z0-9_]+)"', js))
    assert called <= set(docs), sorted(called - set(docs))                       # nothing in the UI points at a missing definition
    quoted = set(re.findall(r'"([a-z0-9_]+)"', js))
    dead = sorted(set(docs) - quoted)
    assert not dead, f"documented but never shown in the UI: {dead}"            # no dead documentation


def _db(n=40):
    db = os.path.join(_scratch.mkdtemp(), "t.db")
    init_db.migrate(db)
    c = sqlite3.connect(db)
    d0 = date(2026, 1, 1)
    for i in range(n):
        t = (d0 + timedelta(days=i)).isoformat() + "T00:00:00Z"
        a = (d0 + timedelta(days=i)).isoformat() + "T21:00:00Z"
        ingest.record_observation(c, agent_id="Agent_NGL_MontBelvieu_Propane", target_timestamp=t, available_timestamp=a, value=80 + (i % 9), source_id="eia_dnav_pet", unit="cents/gal")
        ingest.record_observation(c, agent_id="Agent_Crude_WTI_Spot", target_timestamp=t, available_timestamp=a, value=84.0, source_id="eia_dnav_pet", unit="USD/bbl")
    c.commit()
    c.close()
    return db


def test_payload_serves_explain_price_lineage_and_roster_descriptions():
    st = me.build_state(_db(), as_of="2026-12-31T00:00:00Z")
    assert set(st["explain"]) == set(me.explain())
    p = st["price"]
    assert p["agent_id"] == "Agent_NGL_MontBelvieu_Propane" and p["source_id"] == "eia_dnav_pet" and "retrieved_timestamp" in p and "quality_status" in p and "raw_payload_hash" in p
    by = {s["agent_id"]: s for s in st["sources"]}
    cash = by["Agent_HH_Cash_Midpoint"]
    assert cash["status"] == "pending_collector" and "Daily volume-weighted cash index" in cash["series"] and "NGI" in cash["intended_source"]
    assert by["Agent_Flow_Kingsgate"]["intended_source"].startswith("TC Energy")
