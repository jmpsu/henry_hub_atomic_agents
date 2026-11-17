"""G5 modules: A (lng_feedgas), B (frac_module), the M1-M7 classification (fundamentals) and the METAR collector (F5)."""
import ast
import json
import math
import sqlite3
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import frac_module as fm  # noqa: E402
import fundamentals as fu  # noqa: E402
import ingest  # noqa: E402
import init_db  # noqa: E402
import lng_feedgas as lg  # noqa: E402
import markets_engine as me  # noqa: E402
from collectors import metar_ambient as mt  # noqa: E402


def _db():
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    return db


def _seed_exports(db, months=40, rate_mmcfd=3300.0, start=(2023, 1), skip_terminal=None):
    """Monthly volume = rate x days in the month, so the per-day rate is exactly flat (a constant monthly volume would wobble with the calendar)."""
    import calendar
    c = sqlite3.connect(db)
    y, m = start
    for i in range(months):
        yy, mm = y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1
        for t, agent in lg.TERMINALS.items():
            if t == skip_terminal:
                continue
            ingest.record_observation(c, agent_id=agent, target_timestamp=f"{yy}-{mm:02d}-01T00:00:00Z", available_timestamp=f"{yy}-{mm:02d}-28T00:00:00Z", value=rate_mmcfd * calendar.monthrange(yy, mm)[1], source_id="eia_test",
                                      unit="MMcf/month", quality_status="official")
    c.commit()
    c.close()
    return db


# ----------------------------------------------------------------------------- Module A
def test_module_a_refuses_every_price_and_demand_weather_input():
    for bad in ("Agent_HH_M1", "Agent_TTF_2026_12", "Agent_FX_EURUSD", "Agent_NGL_MontBelvieu_Ethane", "Agent_Weather_Actual_HDD", "Agent_GFS_00z_HDD_Day1",
                "Agent_ECMWF_00z_HDD_Day1", "Agent_Storage_East", "Agent_Charter_Rate_X", "Agent_Basis_HSC"):
        with pytest.raises(ValueError):
            lg.assert_inputs([bad])
    lg.assert_inputs(["Agent_LNGExports_SabinePass", "Agent_AmbientTemp_KLCH", "Agent_AmbientDew_KLCH", "Agent_AmbientPress_KCRP"])


def test_module_a_is_isolated_from_the_pricing_engine():
    imports = set()
    for node in ast.walk(ast.parse((ROOT / "lng_feedgas.py").read_text())):
        if isinstance(node, ast.Import):
            imports |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports & {"markets_engine", "lng_forward", "lng_config", "lng_evidence", "markets_hub"}


def test_log_changes_ignore_a_new_terminal_and_gaps():
    m = [("2024-01", 10.0, frozenset("AB")), ("2024-02", 11.0, frozenset("AB")), ("2024-03", 15.0, frozenset("ABC")),     # C appears: not growth of A and B
         ("2024-04", 15.0, frozenset("ABC")), ("2024-07", 16.0, frozenset("ABC"))]                                          # a 3-month gap: not a monthly change
    ch = lg.log_changes(m)
    assert len(ch) == 2 and ch[0] == pytest.approx(math.log(1.1)) and ch[1] == 0.0


def test_stationary_bootstrap_exact_on_constant_changes_and_reproducible():
    rng = np.random.default_rng(1)
    s = lg.stationary_bootstrap_sums([0.01] * 20, 3.0, 50, 3.0, rng)
    assert np.allclose(s, 0.03)
    s2 = lg.stationary_bootstrap_sums([0.01] * 20, 2.5, 50, 3.0, np.random.default_rng(1))
    assert np.allclose(s2, 0.025)                                                    # fractional last month is pro-rated
    a = lg.stationary_bootstrap_sums(list(np.linspace(-0.05, 0.05, 30)), 3.2, 200, 3.0, np.random.default_rng(7))
    b = lg.stationary_bootstrap_sums(list(np.linspace(-0.05, 0.05, 30)), 3.2, 200, 3.0, np.random.default_rng(7))
    assert np.array_equal(a, b)


def test_wet_bulb_matches_stull_reference():
    assert lg.wet_bulb_c(20.0, 9.3) == pytest.approx(13.7, abs=0.2)                  # 20 C at about 50 % RH
    assert lg.wet_bulb_c(30.0, 30.0) == pytest.approx(30.0, abs=0.6)                 # saturated: wet bulb = air temperature


def test_estimate_flat_history_is_the_anchor_times_the_fuel_uplift_and_percentiles_are_ordered():
    db = _seed_exports(_db(), months=40, rate_mmcfd=3300.0)                          # 8 terminals x 3,300 MMcf/d = 26.4 Bcf/d, flat
    c = sqlite3.connect(db)
    est = lg.estimate(c, "2026-06-15T00:00:00Z")                                     # last row is 2026-04
    assert est["status"] == "estimate" and est["anchor_month"] == "2026-04" and est["provenance"] == "bootstrapped_physical_proxy"
    anchor = 8 * 3300 / 1000                                                           # 26.4 Bcf/d
    assert est["anchor_exports_bcfd"] == pytest.approx(anchor, abs=1e-3)
    assert est["p10"] <= est["p50"] <= est["p90"]
    assert anchor * 1.08 - 1e-3 <= est["p10"] and est["p90"] <= anchor * 1.10 + 1e-3  # zero growth history -> only the 8-10 % uplift spreads the result
    assert est["n_iterations"] == 1000 and est["evidence"]["ebb_scheduled_quantity"] == 0 and {x["id"] for x in est["not_used"]} == {"F1", "F2", "F3", "F4", "F8"}
    assert lg.estimate(c, "2026-06-15T00:00:00Z")["p50"] == est["p50"]                # deterministic seed


def test_estimate_is_point_in_time_and_pending_without_history():
    db = _seed_exports(_db(), months=40)
    c = sqlite3.connect(db)
    early = lg.estimate(c, "2024-06-15T00:00:00Z")                                    # only the months published by then
    assert early["status"] == "estimate" and early["anchor_month"] == "2024-05"    # May is published (28th) before 15 June; June is not
    assert lg.estimate(c, "2023-01-01T00:00:00Z")["status"] == "pending_collector"    # nothing published yet
    few = lg.estimate(sqlite3.connect(_seed_exports(_db(), months=8)), "2024-01-01T00:00:00Z")
    assert few["status"] == "pending_collector" and "usable month-over-month changes" in few["reason"]


def test_store_writes_the_three_series_with_the_required_tag_and_is_idempotent(tmp_path):
    db = _seed_exports(_db(), months=40)
    c = sqlite3.connect(db)
    est = lg.estimate(c, "2026-06-15T00:00:00Z")
    assert lg.store(c, est, "2026-06-15T01:00:00Z") == 3 and lg.store(c, est, "2026-06-15T01:00:00Z") == 0
    rows = c.execute("SELECT agent_id, series_id, provenance, value FROM pit_market_data WHERE agent_id LIKE 'Agent_LNGFeedgas_%' ORDER BY agent_id").fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("Agent_LNGFeedgas_P10", "lng_feedgas_p10", "bootstrapped_physical_proxy"), ("Agent_LNGFeedgas_P50", "lng_feedgas_p50", "bootstrapped_physical_proxy"),
                                                  ("Agent_LNGFeedgas_P90", "lng_feedgas_p90", "bootstrapped_physical_proxy")]
    assert lg.store(c, {"status": "pending_collector"}) == 0
    out = tmp_path / "f.json"
    out.write_text(json.dumps({**est, "available_timestamp": "2026-06-15T01:00:00Z"}))
    assert lg.load("2026-06-15T00:59:59Z", out) is None and lg.load("2026-06-15T01:00:00Z", out)["p50"] == est["p50"]
    assert lg.load("2026-06-15T01:00:00Z", tmp_path / "missing.json") is None


# ----------------------------------------------------------------------------- Module B
def test_frac_rejection_hand_computed():
    ev = fm.ethane_usd_mmbtu(25.0)
    assert ev == pytest.approx(0.25 / 0.0664)                                          # 3.7651
    assert fm.tf_usd_mmbtu() == pytest.approx(0.08 / 0.0664)                           # 1.2048
    r = fm.rejection(ev, 3.0)
    margin = ev - (3.0 + 0.08 / 0.0664)                                                # -0.4398
    assert r["regime"] == "REJECTION" and r["margin_usd_mmbtu"] == pytest.approx(margin)
    d = r["net_dry_gas_delta_bcfd"]
    assert d["low"] == pytest.approx(-margin * 0.5) and d["central"] == pytest.approx(-margin * 1.0) and d["high"] == pytest.approx(-margin * 1.5)


def test_frac_recovery_and_cap():
    assert fm.rejection(fm.ethane_usd_mmbtu(40.0), 3.0)["net_dry_gas_delta_bcfd"] == {"low": 0.0, "central": 0.0, "high": 0.0}
    assert fm.rejection(fm.ethane_usd_mmbtu(40.0), 3.0)["regime"] == "RECOVERY"
    assert fm.rejection(fm.ethane_usd_mmbtu(5.0), 3.0)["net_dry_gas_delta_bcfd"]["high"] == pytest.approx(1.5)       # capped at the stated swing


def _row(v, avail="2026-11-16T12:00:00Z", prov="measured"):
    return {"value": v, "latest_target_timestamp": "2026-11-16T00:00:00Z", "available_timestamp": avail, "provenance": prov}


def test_frac_module_pending_records_the_exact_blockers_and_never_guesses():
    out = fm.build(None, _row(3.0), None, "2026-11-17T12:00:00Z")
    assert out["status"] == "pending_collector" and [b["input"] for b in out["blocked"]] == ["Agent_NGL_MontBelvieu_Ethane"]
    assert out["waha"]["status"] == "BLOCKED" and "Waha" in out["waha"]["reason"] and "net_dry_gas_delta_bcfd" not in out
    assert fm.build(_row(25.0, avail="2026-10-01T00:00:00Z"), _row(3.0), None, "2026-11-17T12:00:00Z")["status"] == "pending_collector"      # stale ethane
    assert fm.build(_row(25.0, prov="unverified_seed"), _row(3.0), None, "2026-11-17T12:00:00Z")["status"] == "pending_collector"          # a seed is not a measurement


def test_frac_module_estimate_is_labelled_and_only_the_delta_leaves_it():
    out = fm.build(_row(25.0), _row(3.0), None, "2026-11-17T12:00:00Z")
    assert out["status"] == "estimate" and out["regime"] == "REJECTION" and out["hub"].startswith("Henry Hub")
    assert out["assumptions"]["tf_cost"]["kind"] == "assumption" and out["assumptions"]["recovery_swing"]["value"] == [0.5, 1.5]
    assert out["feeds_forward_balance"] is False and "net_dry_gas_delta_bcfd" in out["output_contract"]
    assert fm.build(_row(25.0, avail="2026-11-18T00:00:00Z"), _row(3.0), None, "2026-11-17T12:00:00Z")["status"] == "pending_collector"   # not yet available at the cutoff


def test_engine_uses_the_single_ethane_constant():
    assert me.ETHANE_MMBTU_PER_GAL == fm.ETHANE_MMBTU_PER_GAL == 0.0664


# ----------------------------------------------------------------------------- M1-M7 classification
def test_value_at_interpolates_between_months_and_holds_after_the_last():
    pts = [("2026-08-01", 10.0), ("2026-09-01", 20.0)]
    mid = fu.value_at(pts, "2026-09-01")                                              # exactly halfway between the two mid-month anchors (Aug 15 .. Sep 15)
    assert mid["mode"] == "interpolated" and 10 < mid["value"] < 20
    held = fu.value_at(pts, "2026-11-17")
    assert held["mode"] == "held" and held["value"] == 20.0 and held["lag_days"] == 63                   # extrapolation refused, lag stated
    assert fu.value_at(pts, "2026-01-01")["mode"] == "before_range" and fu.value_at([], "2026-01-01") is None


def test_classification_covers_m1_to_m7_and_no_element_claims_to_move_a_price(tmp_path):
    db = _db()
    c = sqlite3.connect(db)
    ingest.record_observation(c, agent_id="Agent_Prod_Permian", target_timestamp="2026-10-01T00:00:00Z", available_timestamp="2026-11-05T00:00:00Z", value=28.0, source_id="eia", unit="Bcf/d")
    c.commit()
    blk = me.build_state(db, as_of="2026-11-17T12:00:00Z")["fundamentals"]
    ids = [e["id"] for e in blk["elements"]]
    assert ids == ["M1", "M2", "M3", "M4", "M5", "M6", "M7"]
    assert blk["direct"] == ["M1", "M2", "M3", "M6", "M7"] and blk["separate"] == ["M4", "M5"]
    assert all(e["price_path"]["used_in_price"] is False and "O6" in blk["price_note"] for e in blk["elements"])
    m2 = next(e for e in blk["elements"] if e["id"] == "M2")
    assert "Excluded from the LNG liquefaction" in m2["scope_rule"] and m2["scope_verified"] is True
    assert all(e["frequency"] and e["collector_status"] and "raw_payload_hashes" in e and "feeds_today" in e for e in blk["elements"])
    assert [i["id"] for i in blk["forward_price_inputs"]][:1] == ["P1"] and {d["group"] for d in blk["disposition"]} == {"demand", "crude_and_carbon"}
    m1 = next(e for e in blk["elements"] if e["id"] == "M1")
    assert m1["agents_collected"] == 1 and m1["headline"]["value"] == 28.0 and m1["status"] == "measured"
    m5 = next(e for e in blk["elements"] if e["id"] == "M5")
    assert m5["status"] == "pending_collector" and {b["input"] for b in m5["blocked"]} == {"Agent_NGL_MontBelvieu_Ethane", "Agent_Gas_Waha_Spot", "Agent_HH_Spot_EIA"}        # the temp DB has no Henry Hub spot either


def test_engine_shows_module_a_output_only_when_it_was_available_at_the_cutoff(monkeypatch):
    db = _db()
    doc = {"status": "estimate", "p10": 16.0, "p50": 18.0, "p90": 20.0, "as_of": "2026-11-17T10:00:00Z", "available_timestamp": "2026-11-17T10:00:00Z", "provenance": lg.PROVENANCE,
           "anchor_month": "2026-08", "not_used": lg.NOT_USED}
    monkeypatch.setattr(lg, "load", lambda cutoff, path=None: doc if doc["available_timestamp"] <= cutoff else None)
    after = me.build_state(db, as_of="2026-11-17T12:00:00Z")["fundamentals"]["elements"][3]
    assert after["status"] == "estimate" and after["headline"]["value"] == 18.0 and after["headline"]["p10"] == 16.0 and {b["id"] for b in after["blocked"]} == {"F1", "F2", "F3", "F4", "F8"}
    before = me.build_state(db, as_of="2026-11-17T09:00:00Z")["fundamentals"]["elements"][3]
    assert before["status"] == "pending_collector" and before["headline"] is None


# ----------------------------------------------------------------------------- METAR collector (F5)
SAMPLE = [{"icaoId": "KLCH", "obsTime": 1760000000, "temp": 8.3, "dewp": 3.9, "altim": 1026.5}, {"icaoId": "KCRP", "obsTime": 1760000000, "temp": 10.0, "dewp": None, "altim": 1026.2}]


def _client(payload):
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=json.dumps(payload).encode())))


def test_metar_parse_skips_missing_fields_and_collect_is_point_in_time_and_idempotent(tmp_path):
    assert len(mt.parse(SAMPLE)) == 5                                                  # KCRP dew point missing: skipped, not filled
    assert mt.TERMINAL_STATIONS["SAB"] == "KLCH" and mt.TERMINAL_STATIONS["CRP"] == "KCRP"
    c = sqlite3.connect(_db())
    out = mt.collect(c, str(tmp_path), _client(SAMPLE))
    assert out[0]["observations_new"] == 5 and out[0]["rejected_by_gatekeeper"] == 0
    r = c.execute("SELECT target_timestamp, available_timestamp, unit, provenance FROM pit_market_data WHERE agent_id='Agent_AmbientTemp_KLCH'").fetchone()
    assert r[3] == "measured" and r[2] == "degC" and r[0] < r[1]                        # available = retrieval time, after the observation
    assert mt.collect(c, str(tmp_path), _client(SAMPLE))[0]["observations_new"] == 0
    bad = mt.collect(c, str(tmp_path), _client([{"icaoId": "KLCH", "obsTime": 1760003600, "temp": 999.0}]))
    assert bad[0]["observations_new"] == 0 and bad[0]["rejected_by_gatekeeper"] == 1  # the physical-range gate refuses it
    assert mt.collect(c, str(tmp_path), httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500))))[0]["error"]


def test_m7_is_the_net_of_canadian_imports_and_mexican_exports():
    mk = lambda v: {"value": v, "latest_target_timestamp": "2026-08-01T00:00:00Z", "available_timestamp": "2026-10-31T00:00:00Z", "provenance": "measured"}
    latest = {"Agent_BorderFlow_Eastport_FromCanada": mk(100_000.0), "Agent_BorderFlow_Noyes_FromCanada": mk(50_000.0), "Agent_BorderFlow_RioGrande_ToMexico": mk(120_000.0)}
    ga = {"border_flows": list(latest)}
    m7 = fu.build(latest, ga, {}, None, fm.build(None, None, None, "2026-11-17T12:00:00Z"), "2026-11-17T12:00:00Z")["elements"][6]
    assert m7["headline"]["value"] == pytest.approx(30.0) and m7["headline"]["imports_canada_bcf"] == 150.0 and m7["headline"]["exports_mexico_bcf"] == 120.0


def test_kb_declares_the_requirement_edges_without_claiming_measured_causation(tmp_path):
    import kb_ingest as kb
    db = _db()
    kb.ingest(db, embedder=lambda t: [1.0, 0.0, 0.0], now="2026-11-17T12:00:00Z")
    c = sqlite3.connect(db)
    edges = {(t,) for (t,) in c.execute("SELECT type FROM kb_edges")}
    for t in ("feeds_supply", "feeds_rescomm_demand", "feeds_inventory_balance", "calibrated_by", "modifies_dry_gas_supply", "feeds_net_exports"):
        assert (t,) in edges
    assert c.execute("SELECT COUNT(*) FROM kb_edges WHERE type IN ('feeds_supply','feeds_rescomm_demand','feeds_inventory_balance','modifies_dry_gas_supply','feeds_net_exports')").fetchone()[0] == 5
    cal = c.execute("SELECT a.title, b.title FROM kb_edges e JOIN kb_nodes a ON a.id=e.src JOIN kb_nodes b ON b.id=e.dst WHERE e.type='calibrated_by'").fetchone()
    assert cal[0].startswith("M4") and cal[1].startswith("M6")
    fpm = c.execute("SELECT document FROM kb_nodes WHERE title='Forward_Pricing_Model'").fetchone()[0]
    assert "DECLARED" in fpm and "none of them changes a price today" in fpm.replace("so none of them", "none of them") or "changes a price today" in fpm
    kb.ingest(db, embedder=lambda t: [1.0, 0.0, 0.0], now="2026-11-17T13:00:00Z")           # a re-ingest keeps them (rebuild_edges only recomputes derived types)
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM kb_edges WHERE type='feeds_supply'").fetchone()[0] == 1
    assert "no calculation consumes" in kb.EDGE_LEGEND["feeds_supply"]
