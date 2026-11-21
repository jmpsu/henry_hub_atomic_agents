"""Drill-down (docs/DRILLDOWN_SPEC.md, checklist D-V1..D-V3 and the endpoint contract).
V1  every metric: recompute the value from the L4 leaves using only the formula in the trace, equal to the displayed value at its displayed precision
V2  every leaf has t_available <= cutoff
V3  a pending operand produces `withheld`, never a number"""
import hashlib
import importlib
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import derivation as dv  # noqa: E402
import ingest  # noqa: E402
import init_db  # noqa: E402
import markets_engine as me  # noqa: E402

END = date(2026, 11, 11)
CUT = "2026-11-17T12:00:00Z"


def _walk(rng, n, start, step, lo):
    x, out = start, []
    for _ in range(n):
        x = max(lo, x + rng.normal(0, step))
        out.append(round(float(x), 3))
    return out


def seed(ethane=True, conway=True, final=None, n=420):
    """A complete synthetic database: 420 daily sessions of every series the page uses, plus a forward curve, TTF/FX, storage, production, weather and notices."""
    d = Path(_scratch.mkdtemp())
    db = str(d / "t.db")
    init_db.migrate(db)
    c = sqlite3.connect(db)
    rng = np.random.default_rng(11)
    days = [END - timedelta(days=n - 1 - i) for i in range(n)]

    def put(agent, series, unit, vals, source="eia_test", prov="measured", q="official", shift=1):
        for dd, v in zip(days, vals):
            ingest.record_observation(c, agent_id=agent, target_timestamp=f"{dd}T00:00:00Z", available_timestamp=f"{dd + timedelta(days=shift)}T00:00:00Z", value=v, source_id=source, unit=unit,
                                      series_id=series, quality_status=q, provenance=prov, retrieved_timestamp=f"{dd + timedelta(days=shift)}T00:00:00Z", published_timestamp=f"{dd}T20:00:00Z")
    c3 = _walk(rng, n, 90, 2.0, 40)
    wti = _walk(rng, n, 85, 1.5, 40)
    if final:
        c3[-1], wti[-1] = final
    put("Agent_NGL_MontBelvieu_Propane", "Mont Belvieu propane", "cents/gal", c3)
    put("Agent_Crude_WTI_Spot", "WTI", "USD/bbl", wti)
    hh = _walk(rng, n, 3.0, 0.08, 1.5)
    put("Agent_HH_Spot_EIA", "Henry Hub spot", "USD/MMBtu", hh)
    if ethane:
        put("Agent_NGL_MontBelvieu_Ethane", "Mont Belvieu ethane", "cents/gal", _walk(rng, n, 25, 0.8, 12))
    if conway:
        put("Agent_NGL_Conway_Propane", "Conway propane", "cents/gal", [round(v - 4, 3) for v in c3])
    for i, a in enumerate(["Agent_Prod_Appalachia", "Agent_Prod_Permian", "Agent_Prod_Haynesville", "Agent_Prod_EagleFord", "Agent_Prod_Bakken", "Agent_Prod_DJBasin"]):
        ingest.record_observation(c, agent_id=a, target_timestamp="2026-10-01T00:00:00Z", available_timestamp="2026-11-05T00:00:00Z", value=10.0 + i, source_id="eia_test", unit="Bcf/d")
    for a in me.DRIVER_GROUPS[2][2]:
        ingest.record_observation(c, agent_id=a, target_timestamp="2026-11-06T00:00:00Z", available_timestamp="2026-11-12T00:00:00Z", value=640.0, source_id="eia_test", unit="Bcf")
    ingest.record_observation(c, agent_id="Agent_Weather_Actual_HDD", target_timestamp="2026-11-15T00:00:00Z", available_timestamp="2026-11-16T00:00:00Z", value=21.5, source_id="noaa_test", unit="population-weighted degree days")
    ingest.record_observation(c, agent_id="Agent_Weather_30YrNormal_HDD", target_timestamp="2026-11-15T00:00:00Z", available_timestamp="2026-11-01T00:00:00Z", value=18.0, source_id="derived", unit="population-weighted degree days",
                              provenance="extracted_estimate", quality_status="derived_validated")
    for m in range(1, 13):
        ym = f"2026-{12 + (m - 1) % 1:02d}" if m == 1 else f"2027-{m - 1:02d}"
        ingest.record_observation(c, agent_id=f"Agent_HH_M{m}", target_timestamp="2026-11-17T00:00:00Z", available_timestamp="2026-11-17T09:40:00Z", value=round(3.1 + 0.05 * ((m * 5) % 7), 3), source_id="yahoo_finance_nymex",
                                  unit="USD/MMBtu", series_id=f"NG{'FGHJKMNQUVXZ'[m % 12]}27.NYM ({ym})", quality_status="delayed_quote_unverified", provenance="measured", published_timestamp="2026-11-17T09:30:00Z",
                                  retrieved_timestamp="2026-11-17T09:40:00Z")
    for ym, p in (("2026_12", 84.855), ("2027_01", 86.43)):
        ingest.record_observation(c, agent_id=f"Agent_TTF_{ym}", target_timestamp="2026-11-17T00:00:00Z", available_timestamp="2026-11-17T11:40:00Z", value=p, source_id="yahoo_finance_nymex", unit="EUR/MWh",
                                  quality_status="delayed_quote_unverified", published_timestamp="2026-11-17T11:38:27Z", retrieved_timestamp="2026-11-17T11:40:00Z")
    ingest.record_observation(c, agent_id="Agent_FX_EURUSD", target_timestamp="2026-11-17T00:00:00Z", available_timestamp="2026-11-17T11:40:00Z", value=1.0995, source_id="yahoo_finance_nymex", unit="USD/EUR",
                              quality_status="delayed_quote_unverified", published_timestamp="2026-11-17T11:38:00Z", retrieved_timestamp="2026-11-17T11:40:00Z")
    for i, a in enumerate(me.DRIVER_GROUPS[7][2]):
        ingest.record_observation(c, agent_id=a, target_timestamp="2026-08-01T00:00:00Z", available_timestamp="2026-10-31T00:00:00Z", value=60000.0 + 1000 * i, source_id="eia_test", unit="MMcf/month")
    for i, a in enumerate(me.DRIVER_GROUPS[8][2]):
        ingest.record_observation(c, agent_id=a, target_timestamp="2026-08-01T00:00:00Z", available_timestamp="2026-10-31T00:00:00Z", value=20000.0 + 500 * i, source_id="eia_test", unit="MMcf/month")
    for k, v in (("P10", 16.0), ("P50", 18.0), ("P90", 20.0)):
        ingest.record_observation(c, agent_id=f"Agent_LNGFeedgas_{k}", target_timestamp="2026-11-16T00:00:00Z", available_timestamp="2026-11-16T12:00:00Z", value=v, source_id="lng_feedgas_model", unit="Bcf/d",
                                  provenance="bootstrapped_physical_proxy", quality_status="monthly_anchor_bootstrap_no_ebb_ais", series_id=f"lng_feedgas_{k.lower()}")
    c.execute("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, domain TEXT, source_id TEXT, source_url TEXT, title TEXT, body TEXT, published_timestamp TEXT, available_timestamp TEXT, "
              "retrieved_timestamp TEXT, raw_payload_hash TEXT, extraction_version TEXT, provenance TEXT)")
    for i, (body, av) in enumerate((("Notice A. FORCE MAJEURE. Station 1", "2026-11-14T10:00:00Z"), ("Notice B routine maintenance", "2026-11-15T10:00:00Z"), ("Old notice", "2026-09-01T10:00:00Z"))):
        c.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (f"n{i}", "pipeline_notice", "kinder_morgan_notices_tgp", "u", f"Notice {i}", body, av, av, av, "", "x", "source_document"))
    c.commit()
    c.close()
    return db


@pytest.fixture(scope="module")
def full_db():
    return seed(final=(106.1, 89.62))


IDS = ["price", "change_1d", "change_1d_pct", "change_5d", "change_5d_pct", "window_high", "window_low", "sma20", "sma50", "sma200", "trend", "ma_regime", "rsi14", "macd_line", "macd_signal",
       "macd_hist", "bb_upper", "bb_lower", "bandwidth", "squeeze", "tri_upper", "tri_lower", "divergence:rsi", "divergence:macd", "fib:0.0", "fib:0.236", "fib:0.382", "fib:0.5", "fib:0.618",
       "fib:0.786", "fib:1.0", "fib_high", "fib_low", "fib_retrace", "fib_golden", "pct_of_wti", "frac_spread", "hub_spread", "fwd:M1", "fwd:M7", "fwd:M12", "fwd_front_spread", "fwd_span", "regime",
       "lng_fob:M1", "lng_fob:M12", "lng_netback:M1", "lng_netback:M2", "lng_netback:M3", "shale_total", "storage_total", "hdd_anomaly", "flow_count", "notices_7d", "notices_7d:TGP", "fm_30d",
       "seasonal_avg", "seasonal_min", "seasonal_max", "tri_pattern", "lng_exports_total", "border_net", "feedgas:p50", "feedgas:p10", "drv:Agent_HH_Spot_EIA", "drv:Agent_Storage_East", "geo:SAB", "geo:MBV"]


def reachable(t: dv.Trace, root: str) -> list:
    seen, stack = [], [root]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.append(nid)
        stack += [o["id"] for o in t.nodes[nid]["operands"]]
    return seen


def same(a, b, d):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) or isinstance(b, str) or isinstance(a, bool) or isinstance(b, bool):
        return a == b
    return round(a, d) == round(b, d) or abs(a - b) <= 10 ** -(d + 1)


def displayed(state, mid):
    """The number the page itself displays for this metric, taken from the same payload."""
    s, tch, c, dr = state, state["technicals"].get("summary", {}), state["curves"], state["derived"]
    pr = s["price"]
    table = {"price": pr.get("value"), "change_1d": pr.get("change_1d"), "change_1d_pct": pr.get("change_1d_pct"), "change_5d": pr.get("change_5d"), "change_5d_pct": pr.get("change_5d_pct"),
             "window_high": pr.get("window_high"), "window_low": pr.get("window_low"), "sma50": tch.get("sma50"), "sma200": tch.get("sma200"), "trend": tch.get("trend"), "ma_regime": tch.get("ma_regime"),
             "rsi14": tch.get("rsi14"), "macd_hist": tch.get("macd_hist"), "bandwidth": tch.get("bandwidth_pct"), "squeeze": tch.get("bollinger_squeeze"), "divergence:rsi": tch.get("divergence_rsi"),
             "divergence:macd": tch.get("divergence_macd"), "pct_of_wti": pr.get("pct_of_wti"), "fib_retrace": s["technicals"].get("fibonacci", {}).get("retracement_pct"),
             "fib_golden": s["technicals"].get("fibonacci", {}).get("golden_ratio_distance_pct_of_range"), "fib_high": s["technicals"].get("fibonacci", {}).get("swing_high"),
             "fib_low": s["technicals"].get("fibonacci", {}).get("swing_low"), "shale_total": dr["shale_production_total_bcfd"]["value"], "storage_total": dr["storage_total_bcf"]["value"],
             "hdd_anomaly": dr["hdd_anomaly"]["value"], "regime": c["forward_curve"].get("regime"), "fwd_front_spread": (c["forward_curve"].get("shape") or {}).get("front_spread"),
             "fwd_span": (c["forward_curve"].get("shape") or {}).get("last_minus_first")}
    if "bb" in mid or mid.startswith("fib:") or mid in ("frac_spread", "hub_spread") or mid.startswith("fwd:") or mid.startswith("lng_"):
        pass
    if mid.startswith("fib:") and tch:
        table[mid] = s["technicals"]["fibonacci"]["levels"][f"{float(mid.split(':')[1]) * 100:.1f}%"]
    if mid == "frac_spread" and c["frac_spread"]["status"] == "measured":
        table[mid] = c["frac_spread"]["frac_spread_usd_mmbtu"][-1]
    if mid == "hub_spread" and c["hub_spread"]["status"] == "measured":
        table[mid] = c["hub_spread"]["mont_belvieu"][-1] - c["hub_spread"]["conway"][-1]
    if mid.startswith("fwd:"):
        table[mid] = next((p["value"] for p in c["forward_curve"]["points"] if p["contract"] == mid.split(":")[1]), None)
    if mid.startswith("lng_fob:"):
        table[mid] = next((p["fob_cost"] for p in c["lng_forward"]["points"] if p["contract"] == mid.split(":")[1]), None)
    if mid.startswith("lng_netback:"):
        table[mid] = next(((p.get("netback") or {}).get("value") for p in c["lng_forward"]["points"] if p["contract"] == mid.split(":")[1]), None)
    if mid == "tri_pattern":
        table[mid] = tch.get("triangle")
    if mid == "lng_exports_total":
        table[mid] = next(e for e in s["fundamentals"]["elements"] if e["id"] == "M6")["headline"]["value"]
    if mid == "border_net":
        table[mid] = next(e for e in s["fundamentals"]["elements"] if e["id"] == "M7")["headline"]["value"]
    if mid == "bb_upper":
        table[mid] = s["technicals"]["bollinger"]["upper"][-1]
    if mid == "bb_lower":
        table[mid] = s["technicals"]["bollinger"]["lower"][-1]
    if mid == "sma20":
        table[mid] = s["technicals"]["sma20"][-1]
    if mid == "macd_line":
        table[mid] = s["technicals"]["macd"]["line"][-1]
    if mid == "macd_signal":
        table[mid] = s["technicals"]["macd"]["signal"][-1]
    if mid == "tri_upper":
        table[mid] = s["technicals"]["triangle"].get("breakout_above")
    if mid == "tri_lower":
        table[mid] = s["technicals"]["triangle"].get("breakdown_below")
    return table.get(mid, "n/a")


@pytest.mark.parametrize("product", ["propane", "henry_hub"])
def test_v1_every_metric_recomputes_from_its_leaves_to_the_displayed_precision(full_db, product):
    state = me.build_state(full_db, product, "seasonal", CUT)
    checked = withheld = 0
    for mid in IDS:
        t = dv.Trace(full_db, product, "seasonal", CUT)
        root = t.metric(mid)
        n = t.nodes[root]
        for nid in reachable(t, root):
            m = t.nodes[nid]
            ev = dv.evaluate(t.nodes, nid)
            assert same(ev, m["value"], m["decimals"] + 1 if isinstance(ev, float) else 0) or same(ev, m["value"], m["decimals"]), (mid, nid, ev, m["value"])     # every sub-node, down to the leaves
            if m["status"] == dv.WITHHELD:
                assert m["value"] is None and ev is None, (mid, nid)
        shown = displayed(state, mid)
        if n["status"] == dv.WITHHELD:
            withheld += 1
            assert shown in (None, "n/a") or isinstance(shown, str) and False, (mid, shown)
        elif shown != "n/a":
            assert same(dv.evaluate(t.nodes, root), shown, n["decimals"]), (mid, dv.evaluate(t.nodes, root), shown)         # the recomputed number equals what the page displays
        checked += 1
        t.close()
    assert checked == len(IDS) and checked - withheld >= 40


def test_the_specs_worked_example_pct_wti_reproduces_with_its_steps(full_db):
    t = dv.Trace(full_db, "propane", "seasonal", CUT)
    v = t.view(t.metric("pct_of_wti"))
    assert v["display"] == "49.72" and v["unit"] == "%" and v["cutoff"] == CUT
    assert r"\frac{(P_{C3}/100)\cdot 42}{P_{WTI}} \times 100" in v["formula_tex"] and "106.1" in v["tex_sub"] and "89.62" in v["tex_sub"]
    assert any("44.562" in s for s in v["steps"]) and [o["status"] for o in v["operands"]] == ["ok", "ok"]
    legend = {s["sym"]: s for s in v["symbols"]}
    assert legend["42"]["unit"] == "gal/bbl" and legend["P_{WTI}"]["unit"] == "USD/bbl"
    leaf = t.view(v["operands"][1]["id"])["leaf"]
    for k in ("agent_id", "series", "value", "unit", "t_target", "t_published", "t_retrieved", "t_available", "provenance", "quality_status", "source_id", "intended_source", "raw_payload_hash"):
        assert k in leaf
    assert leaf["value"] == 89.62 and leaf["t_available"] <= CUT


def test_window_operands_list_every_input_row_with_sum_mean_and_sigma(full_db):
    t = dv.Trace(full_db, "propane", "seasonal", CUT)
    v = t.view(t.metric("sma50"))
    assert v["rows_total"] == 50 and len(v["rows"]) == 50 and v["stats"]["n"] == 50
    assert v["stats"]["mean"] == pytest.approx(sum(r["v"] for r in v["rows"]) / 50) and v["stats"]["sum"] == pytest.approx(sum(r["v"] for r in v["rows"])) and v["stats"]["std"] > 0
    big = t.view(t.metric("rsi14"))                                                       # a long window is paged, newest page on request
    assert big["rows_total"] == 420 and len(big["rows"]) == dv.PAGE
    newest = t.view(t.metric("rsi14"), offset=-1, limit=10)
    assert newest["rows"][-1]["d"] == "2026-11-11" and len(newest["rows"]) == 10


def test_v2_every_leaf_is_available_at_the_cutoff_and_no_later_row_leaks_in(full_db):
    for cut in ("2026-06-01T00:00:00Z", "2026-10-01T12:00:00Z", CUT):
        for product in ("propane", "henry_hub"):
            for mid in ("pct_of_wti", "rsi14", "macd_hist", "fib:0.618", "bandwidth", "sma200", "fwd_front_spread", "storage_total", "hdd_anomaly", "lng_fob:M1", "seasonal_avg"):
                t = dv.Trace(full_db, product, "seasonal", cut)
                root = t.metric(mid)
                for nid in reachable(t, root):
                    lf = t.nodes[nid].get("leaf")
                    if lf and lf.get("value") is not None:
                        assert lf["t_available"] <= cut, (cut, mid, nid, lf["t_available"])
                    for r in t.nodes[nid]["rows"] or []:
                        assert r["d"] <= cut[:10], (cut, mid, nid, r["d"])                 # window rows come only from vintages available at the cutoff
                    assert t.view(nid)["cutoff"] == cut
                t.close()
    t = dv.Trace(full_db, "propane", "seasonal", "2026-06-01T00:00:00Z")
    assert t.view(t.metric("price"))["leaf"]["t_target"] < "2026-06-01T00:00:00Z"


def test_v3_a_pending_operand_makes_the_parent_withheld_and_never_a_number():
    db = seed(ethane=False, conway=False)
    t = dv.Trace(db, "propane", "seasonal", CUT)
    for mid, agent in (("frac_spread", "Agent_NGL_MontBelvieu_Ethane"), ("hub_spread", "Agent_NGL_Conway_Propane")):
        root = t.metric(mid)
        v = t.view(root)
        assert v["status"] == dv.WITHHELD and v["value"] is None and v["display"] == "withheld" and agent in v["note"]
        pend = [o for o in v["operands"] if o["status"] == dv.WITHHELD]
        assert len(pend) == 1 and pend[0]["display"] == "withheld" and pend[0]["text"] == f"no collector: {agent}"
        leaf = t.view(pend[0]["id"])
        assert leaf["leaf"]["value"] is None and leaf["text"] == f"no collector: {agent}" and "Nothing is filled in" in leaf["note"] and leaf["display"] == "withheld"
        assert dv.evaluate(t.nodes, root) is None
    state = me.build_state(db, "propane", "seasonal", CUT)
    assert state["curves"]["frac_spread"]["status"] == "pending_collector"                    # the page shows nothing for it either
    m = dv.Trace(db, "propane", "seasonal", CUT)
    v = m.view(m.metric("lng_netback:M5"))                                                      # a month with no fresh TTF quote
    assert v["status"] == dv.WITHHELD and "JKM has no free source" in v["note"] and v["display"] == "withheld"


def test_coverage_every_family_listed_in_the_spec_has_a_metric():
    spec = ["price", "change_1d", "change_5d", "sma50", "sma200", "trend", "ma_regime", "rsi14", "macd_line", "macd_signal", "macd_hist", "bandwidth", "squeeze", "tri_upper", "tri_lower", "divergence",
            "fib", "fib_retrace", "fib_golden", "fib_high", "fib_low", "pct_of_wti", "frac_spread", "hub_spread", "fwd", "regime", "fwd_front_spread", "shale_total", "storage_total", "hdd_anomaly",
            "flow_count", "notices_7d", "fm_30d", "seasonal_avg", "seasonal_min", "seasonal_max", "drv", "geo", "lng_fob", "lng_netback", "window_high", "window_low"]
    assert [s for s in spec if s not in dv.METRICS] == []
    assert dv.SHARED_RULE_OPS == {"curve_regime"}


# ----------------------------------------------------------------------------- endpoints
@pytest.fixture(scope="module")
def client(full_db, tmp_path_factory):
    import os
    os.environ["DB_PATH"] = full_db
    for m in ("markets_hub", "chat_service"):
        sys.modules.pop(m, None)
    hub = importlib.import_module("markets_hub")
    from fastapi.testclient import TestClient
    return TestClient(hub.app), hub, full_db


def test_endpoint_schema_validation_and_one_level_at_a_time(client):
    c, hub, db = client
    r = c.get("/api/derivation", params={"metric": "pct_of_wti", "product": "propane", "as_of": CUT})
    j = r.json()
    assert r.status_code == 200 and set(j) == {"metric", "root", "product", "timeframe", "cutoff", "node"} and j["cutoff"] == CUT
    node = j["node"]
    assert {"id", "label", "value", "display", "unit", "cutoff", "formula_tex", "symbols", "tex_sub", "steps", "operands", "status", "op"} <= set(node)
    assert all("operands" not in o for o in node["operands"]) and all(set(o) >= {"id", "label", "display", "status"} for o in node["operands"])        # operands are references, not the whole tree
    child = c.get("/api/derivation", params={"metric": "pct_of_wti", "product": "propane", "as_of": CUT, "node": node["operands"][0]["id"]}).json()["node"]
    assert child["op"] == "leaf" and child["leaf"]["agent_id"] == "Agent_NGL_MontBelvieu_Propane"
    assert c.get("/api/derivation", params={"metric": "nope"}).status_code == 404
    assert c.get("/api/derivation", params={"metric": "price; DROP"}).status_code == 422
    assert c.get("/api/derivation", params={"metric": "price", "as_of": "garbage"}).status_code == 422
    assert c.get("/api/derivation", params={"metric": "price", "node": "leaf:Agent_X:2020-01-01", "product": "propane"}).json()["node"]["status"] == dv.WITHHELD
    assert c.get("/api/derivation", params={"metric": "rsi14", "product": "propane", "rows_offset": -1, "rows_limit": 5}).json()["node"]["rows"][-1]["d"] == "2026-11-11"


def test_raw_endpoint_serves_only_registered_archived_payloads(client, tmp_path):
    c, hub, db = client
    base = Path(db).parent
    (base / "raw").mkdir(exist_ok=True)
    body = b'{"payload": "raw bytes"}'
    sha = hashlib.sha256(body).hexdigest()
    (base / "raw" / sha).write_bytes(body)
    w = sqlite3.connect(db)
    w.execute("INSERT INTO raw_payloads (raw_payload_hash, source_id, source_url, http_status, retrieved_timestamp, content_type, byte_length, archive_path) VALUES (?,?,?,?,?,?,?,?)",
              (sha, "eia_test", "u", 200, "2026-11-17T00:00:00Z", "application/json", len(body), f"raw/{sha}"))
    w.execute("INSERT INTO raw_payloads (raw_payload_hash, source_id, source_url, http_status, retrieved_timestamp, content_type, byte_length, archive_path) VALUES (?,?,?,?,?,?,?,?)",
              ("e" * 64, "eia_test", "u", 200, "2026-11-17T00:00:00Z", "x", 1, "../outside"))
    w.execute("UPDATE pit_market_data SET raw_payload_hash=? WHERE agent_id='Agent_Crude_WTI_Spot' AND target_timestamp LIKE '2026-11-11%'", (sha,))
    w.commit()
    w.close()
    r = c.get(f"/api/raw/{sha}")
    assert r.status_code == 200 and r.content == body and r.headers["content-type"].startswith("text/plain") and r.headers["x-content-type-options"] == "nosniff"
    leaf = c.get("/api/derivation", params={"metric": "pct_of_wti", "product": "propane", "as_of": CUT, "node": "leaf:Agent_Crude_WTI_Spot:2026-11-11"}).json()["node"]["leaf"]
    assert leaf["raw_url"] == f"/api/raw/{sha}" and leaf["raw_payload_hash"] == sha
    assert c.get("/api/raw/" + "e" * 64).status_code == 404                                  # registered but outside the archive directory
    assert c.get("/api/raw/" + "a" * 64).status_code == 404 and c.get("/api/raw/..%2f..%2fetc%2fpasswd").status_code == 404 and c.get("/api/raw/XYZ").status_code == 404


def test_seasonal_band_values_trace_to_the_prior_years_rows_and_match_the_drawn_band():
    db = seed(n=1000)
    state = me.build_state(db, "propane", "seasonal", CUT)
    ov = state["seasonal"]
    assert ov["status"] == "ok" and ov["history_years"]
    t = dv.Trace(db, "propane", "seasonal", CUT)
    doy = date(2026, 11, 11).timetuple().tm_yday
    g = min(ov["day_of_year"], key=lambda x: abs(x - doy))
    gi = ov["day_of_year"].index(g)
    for kind, key in (("avg", "band_avg"), ("min", "band_min"), ("max", "band_max")):
        t = dv.Trace(db, "propane", "seasonal", CUT)
        root = t.metric(f"seasonal_{kind}")
        n_ = t.nodes[root]
        assert n_["status"] == "ok" and len(n_["rows"]) == len(ov["history_years"]) and dv.evaluate(t.nodes, root) == pytest.approx(ov[key][gi])
        assert n_["value"] == pytest.approx(ov[key][gi]) and all(int(r["d"][:4]) in ov["history_years"] for r in n_["rows"])
        t.close()
