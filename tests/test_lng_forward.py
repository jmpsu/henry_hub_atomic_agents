"""LNG forward cost curve: formula vs hand-computed values, no values without Henry Hub points, TTF netback only from fresh PIT-eligible quotes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lng_config as cfg  # noqa: E402
import lng_forward as lf  # noqa: E402

CUT = "2026-11-17T12:00:00Z"


@pytest.fixture(autouse=True)
def pinned(monkeypatch):
    """Pin the assumptions so hand-computed literals hold whatever the defaults are changed to."""
    for k, v in (("FEEDGAS_FACTOR", 1.15), ("LIQUEFACTION_FEE_USD_MMBTU", 2.50), ("SHIPPING_USD_MMBTU", 1.00), ("REGAS_USD_MMBTU", 0.50),
                 ("MMBTU_PER_MWH", 3.412142), ("MAX_QUOTE_AGE_DAYS", 3.0)):
        monkeypatch.setattr(cfg, k, v)


def hh(contract, month, value, **kw):
    return {"contract": contract, "delivery_month": month, "value": value, "date": "2026-11-17", "series_id": f"NG.. ({month})", "source_id": "yahoo_finance_nymex",
            "quality_status": "delayed_quote_unverified", "published_timestamp": "2026-11-17T08:00:00Z", "available_timestamp": "2026-11-17T09:00:00Z", "raw_payload_hash": "abc", **kw}


def quote(value, published="2026-11-17T10:00:00Z", available="2026-11-17T10:05:00Z"):
    return {"value": value, "published_timestamp": published, "available_timestamp": available, "series_id": "TTFZ26.NYM (2026-12)", "quality_status": "delayed_quote_unverified", "raw_payload_hash": "def"}


def test_fob_cost_matches_hand_computed_values_for_three_months():
    pts = [hh("M1", "2026-12", 3.125), hh("M2", "2027-01", 3.503), hh("M5", "2027-04", 2.384)]
    out = lf.build(pts, {}, None, CUT)
    got = {p["delivery_month"]: p for p in out["points"]}
    # 1.15*3.125 = 3.59375 -> +2.50 = 6.09375 ; 1.15*3.503 = 4.02845 -> 6.52845 ; 1.15*2.384 = 2.7416 -> 5.2416
    assert got["2026-12"]["fob_cost"] == pytest.approx(6.09375, abs=1e-9) and got["2026-12"]["feedgas_cost"] == pytest.approx(3.59375, abs=1e-9)
    assert got["2027-01"]["fob_cost"] == pytest.approx(6.52845, abs=1e-9)
    assert got["2027-04"]["fob_cost"] == pytest.approx(5.2416, abs=1e-9)
    assert all(p["liquefaction_fee"] == 2.50 for p in out["points"]) and out["provenance"] == "extracted_estimate" and out["status"] == "estimate"


def test_netback_matches_hand_computed_values():
    # 34.12142 EUR/MWh * 1.0 USD/EUR / 3.412142 MMBtu/MWh = exactly 10.0 USD/MMBtu ; minus shipping 1.00 and regas 0.50 = 8.50 ; FOB 6.09375 -> margin 2.40625
    out = lf.build([hh("M1", "2026-12", 3.125)], {"2026-12": quote(34.12142)}, {"value": 1.0, "published_timestamp": "2026-11-17T11:00:00Z", "available_timestamp": "2026-11-17T11:01:00Z"}, CUT)
    nb = out["points"][0]["netback"]
    assert nb["ttf_usd_mmbtu"] == pytest.approx(10.0, abs=1e-9) and nb["value"] == pytest.approx(8.5, abs=1e-9) and nb["margin_vs_fob_cost"] == pytest.approx(2.40625, abs=1e-9)
    assert out["netback"]["status"] == "estimate" and out["netback"]["points_with_netback"] == 1


def test_no_values_when_henry_hub_points_are_missing():
    out = lf.build([], {"2026-12": quote(80.0)}, {"value": 1.1, "published_timestamp": "2026-11-17T11:00:00Z"}, CUT)
    assert out["status"] == "pending_collector" and out["points"] == [] and "Agent_HH_M1" in out["missing"][0]
    assert out["netback"]["status"] == "pending_collector" and "fob_cost" not in str(out["points"])
    out2 = lf.build([hh("M1", "2026-12", None)], {}, None, CUT)                    # a point without a value is not a point
    assert out2["status"] == "pending_collector" and out2["points"] == []


def test_a_missing_month_gets_no_value_and_present_months_are_unaffected():
    out = lf.build([hh("M1", "2026-12", 3.0), hh("M3", "2027-02", 3.2)], {}, None, CUT)   # M2 absent
    assert [p["contract"] for p in out["points"]] == ["M1", "M3"]


def test_ttf_netback_requires_a_fresh_quote_and_a_fresh_fx():
    fx = {"value": 1.0, "published_timestamp": "2026-11-17T11:00:00Z", "available_timestamp": "2026-11-17T11:01:00Z"}
    pts = [hh("M1", "2026-12", 3.125), hh("M2", "2027-01", 3.503), hh("M3", "2027-02", 3.1)]
    ttf = {"2026-12": quote(34.12142),                                              # fresh
           "2027-01": quote(34.12142, published="2026-11-16T13:44:00Z"),            # 0.94 d old: still fresh
           "2027-02": quote(34.12142, published="2026-10-27T11:20:00Z")}            # 21 d old: stale
    out = lf.build(pts, ttf, fx, CUT)
    by = {p["delivery_month"]: p for p in out["points"]}
    assert by["2026-12"]["netback"] and by["2027-01"]["netback"] and by["2027-02"]["netback"] is None
    assert "last trade" in by["2027-02"]["netback_note"] and "limit 3" in by["2027-02"]["netback_note"]
    assert out["netback"]["points_with_netback"] == 2 and out["netback"]["of"] == 3
    out_nofx = lf.build(pts, ttf, None, CUT)                                        # no EUR/USD quote -> no netback anywhere, never an assumed rate
    assert all(p["netback"] is None for p in out_nofx["points"]) and "EUR/USD: no quote collected" in out_nofx["points"][0]["netback_note"]


def test_pit_a_quote_available_after_the_cutoff_is_not_used():
    fx = {"value": 1.0, "published_timestamp": "2026-11-17T11:00:00Z", "available_timestamp": "2026-11-17T11:01:00Z"}
    late = quote(34.12142, published="2026-11-17T11:30:00Z", available="2026-11-17T13:00:00Z")    # published before the cutoff but retrieved (available) after it
    out = lf.build([hh("M1", "2026-12", 3.125)], {"2026-12": late}, fx, CUT)
    assert out["points"][0]["netback"] is None and "not yet available" in out["points"][0]["netback_note"]


def test_jkm_is_reported_pending_and_assumptions_are_labelled():
    out = lf.build([hh("M1", "2026-12", 3.125)], {}, None, CUT)
    assert "pending a collector" in out["netback"]["jkm"] and "Nothing is estimated" in out["netback"]["jkm"]
    a = out["assumptions"]
    assert a["feedgas_factor"]["kind"] == "assumption" and a["liquefaction_fee"]["kind"] == "assumption" and a["mmbtu_per_mwh"]["kind"] == "physical"
    assert a["liquefaction_fee"]["value"] == 2.50 and a["feedgas_factor"]["value"] == 1.15
