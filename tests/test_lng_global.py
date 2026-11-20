import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))
import _scratch  # noqa: E402
import calibrate_lng_global as cal  # noqa: E402
import init_db  # noqa: E402
import ingest  # noqa: E402
import lng_global as lg  # noqa: E402
import markets_engine as me  # noqa: E402

CUT = "2026-11-20T00:00:00Z"


@pytest.fixture(autouse=True)
def no_external_calibration(monkeypatch, tmp_path):
    monkeypatch.setattr(lg, "CALIBRATION_FILE", tmp_path / "missing_calibration.json")


def test_all_calculations_cover_m1_to_m24_with_ordered_scenario_bands():
    payload = lg.build(cutoff=CUT, scenarios=512)
    assert len(payload["calculations"]) == 20
    assert payload["delivery_months"] == lg._month_sequence(CUT)
    for key, label, unit in lg.CALCULATIONS:
        item = payload["calculations"][key]
        assert item["id"] == label and item["unit"] == unit
        assert len(item["values"]) == 24
        for i, point in enumerate(item["values"]):
            assert point["contract"] == f"M{i + 1}"
            assert point["delivery_month"] == payload["delivery_months"][i]
            assert point["low"] <= point["p25"] <= point["base"] <= point["p75"] <= point["high"]
            assert point["ci_low"] <= point["base"] <= point["ci_high"]
            assert point["model_confidence"] > 0


def test_cpu_simulation_is_deterministic_for_a_fixed_seed():
    params = dict(lg.PARAM_DEFAULTS)
    months = lg._month_sequence(CUT)
    left = lg.simulate(params, months, {}, {}, None, None, 1024, 42)
    right = lg.simulate(params, months, {}, {}, None, None, 1024, 42)
    assert left["diagnostics"]["backend"] == "cpu"
    assert left["diagnostics"]["seed"] == 42
    for key in {name for name, _, _ in lg.CALCULATIONS}:
        np.testing.assert_array_equal(left["arrays"][key], right["arrays"][key])


def test_observed_inputs_are_pit_gated():
    months = lg._month_sequence(CUT)
    fresh = {"value": 80.0, "available_timestamp": "2026-11-19T00:00:00Z"}
    late = {"value": 9.0, "available_timestamp": "2026-11-21T00:00:00Z"}
    payload = lg.build(hh_points=[{"delivery_month": months[0], "value": 3.0, "available_timestamp": None},
                                  {"delivery_month": months[1], "value": 99.0, "available_timestamp": late["available_timestamp"]}],
                       ttf_by_month={months[0]: fresh, months[1]: late}, fx_row=late, oil_row=late, cutoff=CUT, scenarios=256)
    ttf = payload["calculations"]["ttf_forward"]["values"]
    hh = payload["calculations"]["hh_forward"]["values"]
    assert hh[0]["observed"] == 3.0
    assert hh[1]["observed"] is None
    assert ttf[0]["observed"] == 80.0
    assert ttf[1]["observed"] is None


def test_future_calibration_is_ignored_at_an_earlier_cutoff(monkeypatch, tmp_path):
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps({"available_timestamp": "2026-11-21T00:00:00Z", "status": "complete",
                                       "params": {"hh_base": 99.0}, "scenario_count": 1000}))
    monkeypatch.setattr(lg, "CALIBRATION_FILE", calibration)
    payload = lg.build(cutoff=CUT, scenarios=128)
    assert payload["assumptions"]["hh_base"] == lg.PARAM_DEFAULTS["hh_base"]
    assert "after cutoff" in payload["calibration"]["source"]


def test_calibration_helpers_fit_backtest_and_aggregate_reproducibly():
    rows = []
    for i in range(48):
        year, month = 2022 + i // 12, i % 12 + 1
        rows.append((f"{year:04d}-{month:02d}-01T00:00:00Z", 3.2 + 0.5 * math.cos(2 * math.pi * (month - 1) / 12) + i * 0.001))
    seasonal = cal._seasonal_fit(rows)
    assert seasonal["observations"] == 48
    assert seasonal["hh_base"] == pytest.approx(3.2, abs=0.1)
    assert 0.01 <= seasonal["hh_mean_reversion"] <= 0.40
    scores = cal._backtest(rows, seasonal)
    assert set(scores) == {"seasonal_naive", "mean_reverting", "ridge_seasonal", "selected"}
    assert scores["selected"] in ("seasonal_naive", "mean_reverting", "ridge_seasonal")
    assert all(np.isfinite(scores[name][metric]) for name in ("seasonal_naive", "mean_reverting", "ridge_seasonal") for metric in ("rmse", "mae"))
    partials = [{"quantiles": {"hh_forward": [[1], [2], [3], [4], [5]]}}, {"quantiles": {"hh_forward": [[2], [3], [4], [5], [6]]}}]
    aggregated = cal._aggregate_partials(partials, [1, 3])
    assert aggregated["hh_forward"].ravel().tolist() == [1.75, 2.75, 3.75, 4.75, 5.75]


def test_marginal_stack_rises_with_demand_and_feedgas_cost():
    params = dict(lg.PARAM_DEFAULTS)
    shape = (512, 24)
    hh_low = np.full(shape, params["hh_base"] - 1.0)
    hh_high = np.full(shape, params["hh_base"] + 1.0)
    outage = np.zeros(shape)
    low_cost, low_idx = lg._marginal_stack(hh_low, params, lg.ATLANTIC_FACILITIES, 1.0, outage)
    high_demand, high_idx = lg._marginal_stack(hh_low, params, lg.ATLANTIC_FACILITIES, 7.2, outage)
    high_cost, _ = lg._marginal_stack(hh_high, params, lg.ATLANTIC_FACILITIES, 7.2, outage)
    assert float(np.mean(high_demand)) > float(np.mean(low_cost))
    assert float(np.mean(high_cost)) > float(np.mean(high_demand))
    assert int(np.max(high_idx)) > int(np.max(low_idx))


def test_voyage_economics_respond_to_distance_charter_boiloff_and_destination_price():
    params = dict(lg.PARAM_DEFAULTS)
    charter = np.full((64, 24), params["charter_base"])
    fuel = np.full((64, 24), params["fuel_price_base"])
    boil = np.full((64, 24), params["boil_off_rate"])
    dest = np.full((64, 24), 12.0)
    atlantic = lg._voyage("atlantic", charter, fuel, boil, dest, params)
    cape = lg._voyage("cape", charter, fuel, boil, dest, params)
    high_charter = lg._voyage("atlantic", charter * 2, fuel, boil, dest, params)
    high_boil = lg._voyage("atlantic", charter, fuel, boil * 10, dest, params)
    dest[1:, 1] = 30.0
    priced = lg._voyage("atlantic", charter, fuel, boil, dest, params)
    cfg = lg.ROUTES["atlantic"]
    days = cfg["distance_nm"] / (cfg["speed_kn"] * 24.0) + cfg["port_days"] + cfg["canal_days"]
    boil_fraction = 1.0 - np.power(1.0 - boil, days)
    fuel_energy = cfg["fuel_tons_day"] * days * cfg["mmbtu_ton"]
    delivered = cfg["cargo_mmbtu"] * (1.0 - boil_fraction) - fuel_energy
    total_cost = charter * days + cfg["fuel_tons_day"] * days * fuel + cfg["canal_toll"] + cfg["port_charge"] * cfg["cargo_mmbtu"]
    expected_freight = total_cost / delivered
    expected_netback = (12.0 * delivered - total_cost - params["regas_cost"] * delivered - params["loading_cost"] * cfg["cargo_mmbtu"]) / cfg["cargo_mmbtu"]
    np.testing.assert_allclose(atlantic["freight"], expected_freight, rtol=1e-9)
    np.testing.assert_allclose(atlantic["netback"], expected_netback, rtol=1e-9)
    assert cape["days"] > atlantic["days"]
    assert np.all(cape["freight"] > atlantic["freight"])
    assert np.all(high_charter["freight"] > atlantic["freight"])
    assert np.all(high_boil["freight"] > atlantic["freight"])
    assert 1 <= atlantic["arrival_offset"] <= 2
    assert np.mean(priced["netback"][:, 0]) > np.mean(atlantic["netback"][:, 0])


def test_calculation_relationships_and_diagnostics_are_economically_consistent():
    months = lg._month_sequence(CUT)
    result = lg.simulate(dict(lg.PARAM_DEFAULTS), months, {}, {}, None, None, 2048)
    arrays = result["arrays"]
    assert set(arrays) == {key for key, _, _ in lg.CALCULATIONS}
    assert all(array.shape == (2048, 24) and np.all(np.isfinite(array)) for array in arrays.values())
    assert float(np.mean(arrays["terminal_feedgas"])) > float(np.mean(arrays["hh_forward"]))
    assert float(np.mean(arrays["usgc_fob"])) > float(np.mean(arrays["terminal_feedgas"]))
    assert float(np.mean(arrays["jkm_forward"])) > float(np.mean(arrays["ttf_forward"]))
    assert float(np.mean(arrays["spark30s_atlantic_freight"])) > 0
    assert float(np.mean(arrays["usgc_ttf_netback"])) > 0
    assert float(np.mean(arrays["brent_linked_parity"])) > 0
    assert result["diagnostics"]["pacific_route"] in ("Panama", "Cape")
    assert result["diagnostics"]["scenario_count"] == 2048


def test_gpu_backend_matches_structure_when_cuda_is_available():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    months = lg._month_sequence(CUT)
    result = lg.simulate(dict(lg.PARAM_DEFAULTS), months, {}, {}, None, None, 4096, backend="gpu")
    assert result["diagnostics"]["backend"] == "cuda:0"
    assert result["diagnostics"]["device_name"].startswith("NVIDIA")
    assert set(result["arrays"]) == {key for key, _, _ in lg.CALCULATIONS}
    assert all(array.shape == (4096, 24) and np.all(np.isfinite(array)) for array in result["arrays"].values())


def test_market_state_exposes_global_lng_without_replacing_legacy_curve(monkeypatch):
    monkeypatch.setenv("LNG_GLOBAL_SCENARIOS", "256")
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    conn = sqlite3.connect(db)
    ingest.record_observation(conn, agent_id="Agent_HH_M1", target_timestamp="2026-11-20T00:00:00Z", available_timestamp="2026-11-20T09:00:00Z",
                               value=3.0, source_id="yahoo_finance_nymex", unit="USD/MMBtu", series_id="NGZ26.NYM (2026-12)",
                               quality_status="delayed_quote_unverified", published_timestamp="2026-11-20T08:00:00Z")
    conn.commit()
    conn.close()
    state = me.build_state(db, as_of="2026-11-20T12:00:00Z")
    assert "lng_forward" in state["curves"]
    global_curve = state["curves"]["lng_global"]
    assert set(global_curve["calculations"]) == {key for key, _, _ in lg.CALCULATIONS}
    assert global_curve["delivery_months"] == lg._month_sequence("2026-11-20T12:00:00Z")
    assert global_curve["status"] == "modeled" and global_curve["provenance"] == lg.PROVENANCE
    for item in global_curve["calculations"].values():
        assert len(item["values"]) == 24
        assert all(np.isfinite([v["low"], v["p25"], v["base"], v["p75"], v["high"]]).all() for v in item["values"])


def test_all_lng_metrics_are_documented_and_bound_to_the_dashboard():
    docs = me.explain()
    js = (ROOT / "web" / "app.js").read_text()
    html = (ROOT / "web" / "index.html").read_text()
    css = (ROOT / "web" / "app.css").read_text()
    assert 'id="lng-global"' in html and "Global LNG Forward Pricing" in html
    assert "renderLngGlobal(s)" in js and "lng-card-grid" in js and "lng-matrix" in js
    assert "lng-card-grid" in css and "lng-matrix" in css
    assert docs["lng_global"]["params"]["delivery_months"] == lg.DELIVERY_COUNT
    assert docs["lng_global"]["params"]["model_version"] == lg.MODEL_VERSION
    for key, label, _ in lg.CALCULATIONS:
        doc_id = f"lng_{key}"
        assert docs[doc_id]["title"] == label
        assert docs[doc_id]["formula"] and docs[doc_id]["what"] and docs[doc_id]["caveat"]
        assert f'"{doc_id}"' in js
