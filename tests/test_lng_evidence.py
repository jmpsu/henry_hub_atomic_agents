"""O13-R: a knowledge-library value may set an LNG-forward constant only if (1) the quote is a verbatim stored sentence, (2) the number (x100 for a percentage)
literally appears in it, (3) it is inside the sanity band, (4) the params file was available at the PIT cutoff. Otherwise the labelled default is used."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import init_db  # noqa: E402
import ingest  # noqa: E402
import lng_evidence as le  # noqa: E402
import lng_forward as lf  # noqa: E402
import markets_engine as me  # noqa: E402

SPEC_K, SPEC_L = le.PARAMS["k_hh_multiplier"], le.PARAMS["liquefaction_usd_mmbtu"]
Q_K = "Most US export contracts set the feedgas price at 115% of the Henry Hub price plus a fixed fee."
Q_L = "The fixed liquefaction fee in these agreements is typically about 2.25 dollars per MMBtu."


def test_grounding_rules():
    assert le.accept(1.15, Q_K, SPEC_K) is None                         # 115% -> 1.15 is grounded
    assert le.accept(1.2, Q_K, SPEC_K) == "1.2 does not appear in the quoted sentence"
    assert le.accept(2.25, Q_L, SPEC_L) is None
    assert "outside sanity band" in le.accept(9.0, "fee of 9.0 per MMBtu", SPEC_L)
    assert "outside sanity band" in le.accept(1.5, "multiplier of 1.5", SPEC_K)       # band k 1.05-1.30
    assert le.accept(None, Q_L, SPEC_L) == "model found no value in the sentence"


class FakeLLM:
    def __init__(self, value): self.value = value
    def json(self, task, prompt, schema, **kw): return {"value": self.value}


def _quotes(q):
    return lambda *a, **k: {"abstained": False, "quotes": [{"quote": q, "chunk_id": "c1", "doc_id": "d1", "title": "T", "similarity": 0.8,
                                                            "available_timestamp": "2026-11-10T00:00:00Z"}]}


def test_library_value_used_only_when_grounded_and_verbatim(monkeypatch):
    monkeypatch.setattr(le.literature_kb, "verify_quote", lambda *a: True)
    monkeypatch.setattr(le.literature_kb, "best_quotes", _quotes(Q_L))
    good = le.extract_param("liquefaction_usd_mmbtu", SPEC_L, None, FakeLLM(2.25), None, 0)
    assert good["source"] == "library" and good["value"] == 2.25 and good["quote"] == Q_L
    bad = le.extract_param("liquefaction_usd_mmbtu", SPEC_L, None, FakeLLM(3.10), None, 0)      # the model invents a number that is not in the quote
    assert bad["source"] == "assumption" and bad["value"] == 2.50
    monkeypatch.setattr(le.literature_kb, "verify_quote", lambda *a: False)                    # the quote is not a verbatim stored sentence
    assert le.extract_param("liquefaction_usd_mmbtu", SPEC_L, None, FakeLLM(2.25), None, 0)["source"] == "assumption"


def test_abstain_keeps_default(monkeypatch):
    monkeypatch.setattr(le.literature_kb, "best_quotes", lambda *a, **k: {"abstained": True, "quotes": []})
    p = le.extract_param("k_hh_multiplier", SPEC_K, None, FakeLLM(1.15), None, 0)
    assert p["source"] == "assumption" and p["value"] == 1.15


def test_point_in_time_load(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"available_timestamp": "2026-11-17T10:00:00Z", "params": {}}))
    assert le.load("2026-11-17T09:59:59Z", f) is None                   # produced after the cutoff: not visible
    assert le.load("2026-11-17T10:00:00Z", f)["params"] == {}
    assert le.load("2026-11-17T10:00:00Z", tmp_path / "missing.json") is None


def test_validated_drops_tampered_or_ungrounded_library_values_and_keeps_labelled_defaults():
    doc = {"params": {"k_hh_multiplier": {"value": 1.15, "unit": "x Henry Hub", "source": "library", "quote": Q_K},               # ok
                      "liquefaction_usd_mmbtu": {"value": 3.9, "unit": "USD/MMBtu", "source": "library", "quote": Q_L}}}          # 3.9 is in band but not in the quote
    v = le.validated(doc)
    assert "k_hh_multiplier" in v["params"] and "liquefaction_usd_mmbtu" not in v["params"]
    assert "does not appear in the quoted sentence" in v["rejected_at_load"]["liquefaction_usd_mmbtu"]
    out_of_band = le.validated({"params": {"k_hh_multiplier": {"value": 2.0, "source": "library", "quote": "a multiplier of 2.0"}}})
    assert out_of_band["params"] == {} and "outside sanity band" in out_of_band["rejected_at_load"]["k_hh_multiplier"]
    no_quote = le.validated({"params": {"k_hh_multiplier": {"value": 1.15, "source": "library"}}})
    assert no_quote["params"] == {} and le.validated(None) is None
    keep = le.validated({"params": {"k_hh_multiplier": {"value": 1.15, "source": "assumption", "reason": "library abstained"}}})
    assert keep["params"]["k_hh_multiplier"]["reason"] == "library abstained"


HH = [{"contract": "M1", "delivery_month": "2026-12", "value": 3.0, "date": "2026-11-17", "series_id": "x", "source_id": "s", "quality_status": "q",
       "published_timestamp": "p", "available_timestamp": "a", "raw_payload_hash": "h"}]
CUT = "2026-11-17T12:00:00Z"


def test_curve_uses_library_values_and_records_their_source():
    doc = {"generated_at": "g", "context": [{"id": "n1", "title": "Notice"}], "params": {
        "k_hh_multiplier": {"value": 1.15, "unit": "x Henry Hub", "source": "library", "quote": Q_K},
        "liquefaction_usd_mmbtu": {"value": 2.25, "unit": "USD/MMBtu", "source": "library", "quote": Q_L}}}
    c = lf.build(HH, {}, None, CUT, doc)
    p = c["points"][0]
    assert p["fob_cost"] == pytest.approx(5.7, abs=1e-9) and p["liquefaction_fee"] == 2.25 and p["feedgas_cost"] == pytest.approx(3.45, abs=1e-9)          # 1.15*3.0 + 2.25 by hand
    assert c["parameters"]["liquefaction_usd_mmbtu"]["source"] == "library" and c["parameters"]["liquefaction_usd_mmbtu"]["quote"] == Q_L
    assert c["assumptions"]["liquefaction_fee"]["value"] == 2.25 and c["assumptions"]["liquefaction_fee"]["source"] == "library"
    assert c["context"] == [{"id": "n1", "title": "Notice"}] and c["parameters_generated_at"] == "g"


def test_curve_falls_back_to_labelled_defaults_with_a_reason():
    c = lf.build(HH, {}, None, CUT, None)
    assert c["points"][0]["fob_cost"] == pytest.approx(1.15 * 3.0 + 2.50, abs=1e-9) and c["parameters"]["k_hh_multiplier"]["source"] == "assumption"
    assert "not available at the cutoff" in c["parameters"]["k_hh_multiplier"]["reason"]


def test_no_generated_text_enters_the_number_the_value_is_the_printed_number():
    """Even if a params doc claims a different value, load-time validation only passes a value that is printed in the quote."""
    forged = {"params": {"liquefaction_usd_mmbtu": {"value": 2.0, "unit": "USD/MMBtu", "source": "library", "quote": Q_L}}}     # 2.0 is not printed in Q_L
    assert le.validated(forged)["params"] == {}
    c = lf.build(HH, {}, None, CUT, le.validated(forged))
    assert c["points"][0]["liquefaction_fee"] == 2.50


def test_engine_payload_carries_library_parameters(monkeypatch):
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    c = sqlite3.connect(db)
    ingest.record_observation(c, agent_id="Agent_HH_M1", target_timestamp="2026-11-17T00:00:00Z", available_timestamp="2026-11-17T09:00:00Z", value=3.0, source_id="yahoo_finance_nymex",
                              unit="USD/MMBtu", series_id="NGZ26.NYM (2026-12)", quality_status="delayed_quote_unverified", published_timestamp="2026-11-17T08:00:00Z")
    c.commit(); c.close()
    doc = {"available_timestamp": "2026-11-17T10:00:00Z", "generated_at": "2026-11-17T10:00:00Z", "context": [], "params": {
        "liquefaction_usd_mmbtu": {"value": 2.25, "unit": "USD/MMBtu", "source": "library", "quote": Q_L, "title": "Doc", "chunk_id": "c1"}}}
    monkeypatch.setattr(le, "load", lambda cutoff, path=None: doc if doc["available_timestamp"] <= cutoff else None)
    st = me.build_state(db, as_of="2026-11-17T12:00:00Z")["curves"]["lng_forward"]
    assert st["parameters"]["liquefaction_usd_mmbtu"]["source"] == "library" and st["parameters"]["k_hh_multiplier"]["source"] == "assumption"
    assert st["points"][0]["fob_cost"] == pytest.approx(1.15 * 3.0 + 2.25, abs=1e-9)
    mid = me.build_state(db, as_of="2026-11-17T09:30:00Z")["curves"]["lng_forward"]            # HH point exists (09:00) but the params file (10:00) does not yet
    assert mid["status"] == "estimate" and mid["parameters"]["liquefaction_usd_mmbtu"]["source"] == "assumption"
    assert "not available at the cutoff" in mid["parameters"]["liquefaction_usd_mmbtu"]["reason"] and mid["points"][0]["fob_cost"] == pytest.approx(1.15 * 3.0 + 2.50, abs=1e-9)
    early = me.build_state(db, as_of="2026-11-17T08:30:00Z")["curves"]["lng_forward"]          # before any HH point was available: no values at all
    assert early["status"] == "pending_collector" and early["points"] == []
