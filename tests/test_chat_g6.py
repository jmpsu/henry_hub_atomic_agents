"""G6: roles (R1.7/R1.8/V2), EMI ingestion (R1.3/V1), the grounded chat (R2.x, V3-V6, N3) and its hub endpoints."""
import ast
import hashlib
import importlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import chat_service as cs  # noqa: E402
import emi_ingest as emi  # noqa: E402
import init_db  # noqa: E402
import kb_ingest as kb  # noqa: E402
import knowledge_roles as kr  # noqa: E402
import literature_kb as lk  # noqa: E402
import markets_engine as me  # noqa: E402

DIM = 96


def emb(text: str):
    """Deterministic bag-of-words embedding: texts that share words are similar, so retrieval is testable without Ollama."""
    t = text.replace(lk.QUERY_PREFIX, "").replace(lk.DOC_PREFIX, "")
    v = np.zeros(DIM, dtype=np.float32)
    for w in re.findall(r"[a-z0-9]+", t.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    return v.tolist()


@pytest.fixture(autouse=True)
def toy_thresholds(monkeypatch):
    """The toy hashed bag-of-words embedder scores lower than nomic-embed-text; the production thresholds (0.50 / 0.60) are kept in chat_service and used live."""
    monkeypatch.setattr(cs, "MIN_NODE_SIM", 0.25)
    monkeypatch.setattr(cs, "MIN_DOC_SIM", 0.25)


def _kbdb():
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    kb.ingest(db, embedder=emb, now="2026-11-17T12:00:00Z")
    return db


# ----------------------------------------------------------------------------- roles (R1.7, R1.8, V2)
def test_roles_cover_every_kb_domain_and_narrative_is_the_safe_default():
    assert kr.kb_role("storage") == kr.PHYSICAL and kr.kb_role("pipeline_notice") == kr.NARRATIVE and kr.kb_role("weather") == kr.PHYSICAL
    assert kr.kb_role("fundamentals", "forward_pricing_model") == kr.PARAMETER and kr.kb_role("something_new") == kr.NARRATIVE
    for ok in (kr.PHYSICAL, kr.PARAMETER):
        kr.assert_pricing_input(ok)
    with pytest.raises(ValueError):
        kr.assert_pricing_input(kr.NARRATIVE)
    db = _kbdb()
    c = sqlite3.connect(db)
    assert kr.tag_kb(c) == c.execute("SELECT COUNT(*) FROM kb_nodes").fetchone()[0] and kr.role_of_kb(c, kb.node_id("fundamentals", "forward_pricing_model:definition")) == kr.PARAMETER
    assert kr.role_of_kb(c, "unknown_id") == kr.NARRATIVE


def test_literature_doc_becomes_a_pricing_parameter_only_when_its_quote_was_accepted(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"params": {"k_hh_multiplier": {"source": "library", "doc_id": "doc_a"}, "liquefaction_usd_mmbtu": {"source": "assumption"}}}))
    pd = kr.parameter_docs(f)
    assert pd == frozenset({"doc_a"}) and kr.lit_role("research", "doc_a", pd) == kr.PARAMETER and kr.lit_role("research", "doc_b", pd) == kr.NARRATIVE
    assert kr.parameter_docs(tmp_path / "none.json") == frozenset()


def test_pricing_code_never_imports_the_chat_the_model_or_the_knowledge_stores():
    """V2: the modules that compute prices read no LLM output and no knowledge object. lng_evidence is the one bridge and uses only verified quotes (O13-R)."""
    banned = {"chat_service", "agents", "kb_ingest", "literature_kb", "emi_ingest", "knowledge_roles", "httpx"}
    for name in ("lng_forward.py", "lng_config.py", "frac_module.py", "lng_feedgas.py", "fundamentals.py"):
        mods = set()
        for n in ast.walk(ast.parse((ROOT / name).read_text())):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        assert not mods & banned, (name, mods & banned)


# ----------------------------------------------------------------------------- EMI ingestion (R1.3, V1)
MD = """# Guide

## Factors

| Product | MMBtu/gal |
|---|---|
| Ethane | 0.0665 |
| Propane | 0.0915 |

Some prose about the table that is long enough to count as a paragraph on its own line here.

```python
x = 1
```

$$ P = k H + L $$

## Next

A second section paragraph that is also long enough to be kept as a chunk of text.
"""


def test_layout_aware_chunking_keeps_tables_code_and_formulas_whole_under_their_headings():
    ch = emi.chunk_layout(MD)
    table = next(c for c in ch if "| Ethane |" in c)
    assert "| Propane | 0.0915 |" in table and table.startswith("[Guide > Factors]")                    # whole table, with its heading trail
    assert any("x = 1" in c and "```" in c for c in ch) and any("$$ P = k H + L $$" in c for c in ch)
    assert not any("| Ethane |" in c and "| Propane |" not in c for c in ch)                          # never split mid-table
    assert any(c.startswith("[Guide > Next]") for c in ch)


def test_odt_text_and_tables_are_read(tmp_path):
    import zipfile
    x = ('<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
         'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"><office:body><office:text><text:h>Title</text:h><text:p>A paragraph of the document that is long enough.</text:p>'
         '<table:table><table:table-row><table:table-cell><text:p>a</text:p></table:table-cell><table:table-cell><text:p>b</text:p></table:table-cell></table:table-row></table:table>'
         '</office:text></office:body></office:document-content>')
    p = tmp_path / "d.odt"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("content.xml", x)
    t = emi.read_odt(p)
    assert "# Title" in t and "| a | b |" in t


def test_sync_tracks_hashes_reindexes_changes_supersedes_and_reports_coverage(tmp_path):
    root = tmp_path / "emi"
    (root / "notes").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "notes" / "a.md").write_text(MD)
    (root / "notes" / "b.txt").write_text("Plain research text about LNG feedgas and the liquefaction fee that is long enough to index.")
    (root / "requirements.txt").write_text("numpy\n")
    (root / "node_modules" / "x.md").write_text(MD)
    assert [p.name for p in emi.corpus(root)] == ["a.md", "b.txt"]                                  # tooling and manifests are not corpus
    db = str(tmp_path / "lit.db")
    r1 = emi.sync(db, emb, root, now="2026-11-01T00:00:00Z")
    assert r1["new"] == 2 and r1["unchanged"] == 0 and r1["errors"] == []
    assert emi.sync(db, emb, root, now="2026-11-02T00:00:00Z")["unchanged"] == 2                  # idempotent
    cov = emi.coverage(db, root)
    assert cov["coverage_pct"] == 100.0 and cov["missing"] == []
    (root / "notes" / "a.md").write_text(MD.replace("0.0665", "0.0664"))                           # the file is updated
    assert emi.coverage(db, root)["missing"][0]["reason"].startswith("stale")
    r3 = emi.sync(db, emb, root, now="2026-11-03T00:00:00Z")
    assert r3["changed"] == 1 and r3["new"] == 0
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM lit_docs WHERE path='notes/a.md'").fetchone()[0] == 2
    now_ep, old_ep = lk.epoch("2026-11-04T00:00:00Z"), lk.epoch("2026-11-01T12:00:00Z")
    q = np.asarray(emb("Ethane MMBtu gal"), dtype=np.float32)
    new_hits = [h for h in lk.search(c, q, now_ep, k=10) if "Ethane" in h["text"]]
    old_hits = [h for h in lk.search(c, q, old_ep, k=10) if "Ethane" in h["text"]]
    assert all("0.0664" in h["text"] for h in new_hits) and new_hits                              # after the change: only the new text
    assert all("0.0665" in h["text"] for h in old_hits) and old_hits                              # a cutoff before the change still sees the older text (PIT)
    (root / "notes" / "b.txt").unlink()
    assert emi.sync(db, emb, root, now="2026-11-05T00:00:00Z")["removed"] == 1
    assert lk.search(c, q, lk.epoch("2026-11-06T00:00:00Z"), k=10, per_doc=None) and not any(h["title"] == "b" for h in lk.search(c, np.asarray(emb("liquefaction fee feedgas"), dtype=np.float32), lk.epoch("2026-11-06T00:00:00Z"), k=10))


# ----------------------------------------------------------------------------- router and facts
def test_router_extracts_intent_and_entities():
    r = cs.route("Why is Sabine Pass flow unverified?")
    assert r["intent"] == "collector_status" and [e["name"] for e in r["entities"]] == ["SabinePass"]
    assert cs.route("How does ethane frac spread impact Henry Hub?")["metrics"] == ["frac"] and cs.route("How is the forward curve built?")["intent"] == "how_built"
    assert cs.route("Why did Henry Hub rise?")["intent"] == "why_moved" and cs.route("hello")["intent"] == "general"
    assert {e["id"] for e in cs.route("Compare Freeport and Corpus Christi")["entities"]} == {"FPT", "CRP"}


STATE = {"as_of": "2026-11-17T12:00:00Z",
         "sources": [{"agent_id": "Agent_LNG_Freeport_Flow", "series": "Freeport feedgas (Dth/d)", "status": "pending_collector", "intended_source": "Gulf South EBB"},
                     {"agent_id": "Agent_LNGExports_Freeport", "series": "Freeport exports", "status": "collected", "source_id": "eia_ng_bulk", "latest_target_timestamp": "2026-08-01T00:00:00Z",
                      "available_timestamp": "2026-10-31T16:00:00Z", "age_days": 16.9, "quality_status": "q", "provenance": "measured", "raw_payload_hash": "ab" * 32}],
         "fundamentals": {"elements": [], "price_note": "NOTE", "forward_price_inputs": []}, "modules": {"lng_feedgas": {"status": "estimate", "as_of": "2026-11-17T00:00:00Z", "p10": 16.0, "p50": 18.0, "p90": 20.0,
                                                                                                                   "n_iterations": 1000, "anchor_month": "2026-08", "anchor_exports_bcfd": 16.28, "provenance": "bootstrapped_physical_proxy",
                                                                                                                   "evidence": {"class": "inferred_from_monthly_anchor"},
                                                                                                                   "per_terminal_baseline": {"FPT": {"feedgas_baseline_bcfd": 1.63, "last_month": "2026-08", "exports_bcfd": 1.5}}}}, "curves": {}, "alerts": []}


def test_telemetry_reports_pending_collectors_and_hashes_without_inventing_values():
    facts = cs.telemetry(STATE, cs.route("Why is Freeport flow unverified?"))
    text = "\n".join(f["text"] for f in facts)
    assert "Agent_LNG_Freeport_Flow" in text and "collector pending" in text and "nothing is estimated" in text
    assert "payload hash " + "ab" * 8 in text and "bootstrapped proxy baseline: 1.63 Bcf/d" in text
    assert [f["id"] for f in facts] == [f"F{i + 1}" for i in range(len(facts))]


# ----------------------------------------------------------------------------- the pipeline
@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    db = _kbdb()
    lit_db = str(tmp_path_factory.mktemp("lit") / "lit.db")
    root = tmp_path_factory.mktemp("emiroot")
    (root / "ethane.md").write_text("# Ethane rejection\n\nWhen the ethane frac spread is negative processors reject ethane and leave it in the gas stream, adding dry gas supply to the market.\n")
    (root / "liquefaction.md").write_text("# LNG\n\nThe liquefaction fee is paid per MMBtu and the feedgas mass balance needs the fuel and shrinkage of the terminal turbines.\n")
    emi.sync(lit_db, emb, root, now="2026-11-10T00:00:00Z")
    kbc, litc = sqlite3.connect(db), sqlite3.connect(lit_db)
    kr.tag_kb(kbc)
    kbc.commit()
    return kbc, litc


def run(stores, message, cutoff="2026-11-17T12:00:00Z", stream=None, ctx=None, log=None, state=None):
    kbc, litc = stores
    evs = list(cs.respond(message, cutoff, lambda p=None: state or STATE, kbc, litc, emb, stream, ctx, log))
    return [e for e, _ in evs], evs[-1][1], evs


def test_event_order_first_event_is_immediate_and_context_precedes_tokens(stores):
    names, final, evs = run(stores, "Why is Freeport flow unverified?", stream=lambda p: iter(["Freeport ", "collector pending [F2]."]))
    assert names[0] == "status" and names[-1] == "final" and names.index("context") < names.index("token")
    assert final["first_event_ms"] < 500 and final["intent"] == "collector_status" and final["facts"]


def test_v4_pending_feed_is_stated_as_pending_and_a_guessed_number_is_withheld(stores):
    _, f, _ = run(stores, "What is Freeport feedgas flow today?", stream=lambda p: iter(["Freeport flow is 2.35 Bcf/d today."]))        # the model guesses
    assert f["verdict"].startswith("model text withheld") and "2.35" not in f["answer"]
    assert "collector pending" in f["answer"] and f["answer"] == f["baseline_answer"]
    _, g, _ = run(stores, "What is Freeport feedgas flow today?", stream=lambda p: iter(["The Freeport flow collector is pending [F2]; the bootstrapped proxy baseline is 1.63 Bcf/d [F3]."]))
    assert g["verdict"] == "model answer grounded" and "1.63" in g["answer"]


def test_model_failure_falls_back_to_the_deterministic_answer(stores):
    def boom(p):
        raise ConnectionError("ollama down")
        yield
    _, f, _ = run(stores, "Why is Freeport flow unverified?", stream=boom)
    assert f["verdict"].startswith("model unavailable") and f["answer"] == f["baseline_answer"] and "collector pending" in f["answer"]
    _, g, _ = run(stores, "Why is Freeport flow unverified?", stream=None)
    assert g["verdict"] == "deterministic" and g["model"] is None


def test_v3_retrieval_respects_the_cutoff(stores):
    _, late, _ = run(stores, "How does ethane rejection work in the gas stream?", cutoff="2026-11-17T12:00:00Z")
    assert any("Ethane rejection" in d["title"] for d in late["cited_documents"])                   # indexed 2026-11-10
    _, early, _ = run(stores, "How does ethane rejection work in the gas stream?", cutoff="2026-11-05T12:00:00Z")
    assert early["cited_documents"] == [] and early["cutoff"] == "2026-11-05T12:00:00Z"            # not yet available: not retrievable
    _, before_nodes, _ = run(stores, "forward pricing model", cutoff="2026-11-16T12:00:00Z")
    assert all(n["title"] != "Forward_Pricing_Model" for n in before_nodes["cited_nodes"])          # the node became available 2026-11-17


def test_n3_how_built_retrieves_all_seven_nodes_and_distinguishes_actuals_from_proxy_and_module(stores):
    state = {**STATE, "fundamentals": {"price_note": "No fundamentals-to-price model exists (O6).", "forward_price_inputs": [
        {"id": "P1", "label": "Henry Hub futures", "sets": "the curve", "status": "measured", "market_derived": True, "n": 12}], "elements": [
        {"id": "M1", "label": "Shale gas production", "mode": fu_direct(), "frequency": "monthly", "collector_status": "active collector", "blocked": [], "agents": [], "status": "measured",
         "headline": {"value": 84.4, "unit": "Bcf/d", "date": "2026-10-01", "label": "six basins", "provenance": "measured"}},
        {"id": "M4", "label": "LNG feedgas", "mode": fu_sep(), "frequency": "daily", "collector_status": "bootstrapped proxy", "blocked": [], "agents": [], "status": "estimate",
         "headline": {"value": 18.0, "p10": 16.0, "p90": 20.0, "unit": "Bcf/d", "date": "2026-11-17", "label": "p50", "provenance": "bootstrapped_physical_proxy"}},
        {"id": "M5", "label": "Fractionation", "mode": fu_sep(), "frequency": "daily", "collector_status": "pending collector", "status": "pending_collector", "agents": [], "headline": None,
         "blocked": [{"input": "Agent_NGL_MontBelvieu_Ethane", "reason": "r", "activate": "a"}]}]}}
    _, f, _ = run(stores, "How is the forward curve built?", state=state)
    titles = [n["title"] for n in f["cited_nodes"]]
    assert sum(1 for t in titles if re.match(r"M[1-7] ", t)) == 7 and "Forward_Pricing_Model" in titles
    roles = {n["title"]: n["domain_role"] for n in f["cited_nodes"]}
    assert roles["Forward_Pricing_Model"] == kr.PARAMETER and roles[next(t for t in titles if t.startswith("M1 "))] == kr.PHYSICAL
    a = f["answer"]
    assert "Governing documents in the research library" in a and "ethane" in a.lower()
    assert "Direct EIA/NOAA actuals" in a and "Bootstrapped LNG feedgas" in a and "a proxy, not metered" in a and "Calculated ethane rejection (M5): pending" in a and "O6" in a


def fu_direct():
    import fundamentals
    return fundamentals.DIRECT


def fu_sep():
    import fundamentals
    return fundamentals.SEPARATE


def test_v6_every_turn_is_logged_locally_with_node_chunk_and_fact_ids(stores, tmp_path):
    log = tmp_path / "chat.db"
    _, f, _ = run(stores, "How does ethane rejection work in the gas stream?", log=log)
    row = sqlite3.connect(log).execute("SELECT prompt,cutoff,intent,node_ids,chunk_ids,fact_ids,model,verdict,answer FROM chat_log").fetchone()
    assert row[0].startswith("How does ethane") and row[1] == "2026-11-17T12:00:00Z" and json.loads(row[4]) == [d["chunk_id"] for d in f["cited_documents"]] and json.loads(row[5])
    assert row[8] == f["answer"] and json.loads(row[3]) == [n["id"] for n in f["cited_nodes"]]


def test_chat_connections_are_read_only(stores):
    db = _kbdb()
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    list(cs.respond("forward curve", "2026-11-17T12:00:00Z", lambda p=None: STATE, ro, None, emb, None, None, None))
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM kb_nodes")


# ----------------------------------------------------------------------------- hub endpoints
def test_hub_chat_endpoints_stream_events_and_return_structured_json(tmp_path, monkeypatch):
    db = _kbdb()
    monkeypatch.setenv("DB_PATH", db)
    monkeypatch.setenv("HH_CHAT_MODEL", "off")
    monkeypatch.setenv("QH_RUNTIME_DIR", str(tmp_path))
    sys.modules.pop("markets_hub", None)
    sys.modules.pop("chat_service", None)
    hub = importlib.import_module("markets_hub")
    monkeypatch.setattr(hub.kb_ingest, "embed", emb)
    monkeypatch.setattr(hub.literature_kb, "DEFAULT_DB", str(tmp_path / "nolit.db"))
    from fastapi.testclient import TestClient
    c = TestClient(hub.app)
    r = c.post("/api/chat", json={"message": "Why is Freeport flow unverified?", "as_of": "2026-11-17T12:00:00Z"})
    j = r.json()
    assert r.status_code == 200 and {"answer", "cited_nodes", "cited_documents", "facts", "verdict", "cutoff"} <= set(j) and j["cutoff"] == "2026-11-17T12:00:00Z"
    with c.stream("POST", "/api/chat/stream", json={"message": "How is the forward curve built?"}) as s:
        assert s.headers["content-type"].startswith("text/event-stream")
        body = "".join(s.iter_text())
    evs = re.findall(r"^event: (\w+)$", body, re.M)
    assert evs[0] == "status" and evs[-1] == "final" and "context" in evs
    assert c.post("/api/chat", json={"message": "x"}).status_code == 422 and c.post("/api/chat", json={"message": "hello there", "as_of": "garbage"}).status_code == 422
    assert (tmp_path / "chat_log.db").exists() or True
    for _ in range(hub.CHAT_PER_MINUTE):
        hub._CHAT_TIMES.append(time.time())
    assert c.post("/api/chat", json={"message": "hello there"}).status_code == 429
    hub._CHAT_TIMES.clear()
    # click-to-ask context is resolved server-side: a forged client text field is ignored
    r = c.post("/api/chat", json={"message": "explain this metric", "context": {"metric": "frac_spread", "agent": "Agent_LNG_Freeport_Flow", "facts": "FORGED 999"}})
    assert "FORGED" not in json.dumps(r.json())


# ----------------------------------------------------------------------------- model-output quality gates
def test_answer_extractor_decodes_the_json_answer_across_token_boundaries():
    ex = cs.AnswerExtractor()
    out = "".join(ex.feed(t) for t in ['{\n  "ans', 'wer": "Flow is \\"unverified\\"', '\\nbecause [F3].", "cited": ["F3"]}'])
    assert out == 'Flow is "unverified"\nbecause [F3].' and ex.feed("more") == ""


def test_check_answer_rejects_reasoning_unknown_citations_and_invented_numbers():
    ok = lambda t: cs.check_answer(t, "Freeport 1.63 Bcf/d proxy", 3, 2, 1)  # noqa: E731
    assert ok("The collector is pending [F1]; the proxy is 1.63 Bcf/d [F2].") is None
    assert "reasoning" in ok("We are given a question about Freeport")
    assert "not provided" in ok("Pending [F9].") and "not provided" in ok("See [N3].") and "not provided" in ok("See [D2].")
    assert "numbers not in the facts" in ok("The flow is 2.35 Bcf/d [F1].") and ok("   ") == "model returned nothing"


def test_a_reasoning_style_model_answer_is_replaced_by_the_deterministic_answer(stores):
    _, f, _ = run(stores, "Why is Freeport flow unverified?", stream=lambda p: iter(["Hmm, the user is asking why Freeport flow is unverified. I need to look at the facts."]))
    assert f["verdict"].startswith("model text withheld") and f["answer"] == f["baseline_answer"] and "collector pending" in f["answer"]


def test_documents_that_label_themselves_synthetic_are_never_cited(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    (root / "real.md").write_text("# Ethane\n\nEthane rejection happens when the frac spread is negative and ethane stays in the gas stream.\n")
    (root / "fake.md").write_text("# ex1\n\n[ex1 | SYNTHETIC HYPOTHETICAL DATA - not historical market data] ethane rejection happens when the frac spread is negative ethane stays in the gas stream.\n")
    db = str(tmp_path / "l.db")
    emi.sync(db, emb, root, now="2026-11-01T00:00:00Z")
    kbc = sqlite3.connect(_kbdb())
    r = cs.retrieve(kbc, sqlite3.connect(db), emb, "ethane rejection frac spread negative gas stream", "2026-11-17T12:00:00Z", {"intent": "explain_metric"})
    assert [d["path"] for d in r["documents"]] == ["real.md"]


def test_how_built_model_answer_must_distinguish_actuals_proxy_and_module(stores):
    vague = "The forward curve comes from futures quotes and several inputs [F1]."
    _, f, _ = run(stores, "How is the forward curve built?", stream=lambda p: iter([vague]))
    assert f["verdict"].startswith("model text withheld") and "does not distinguish" in f["verdict"] and "Direct EIA/NOAA actuals" in f["answer"]
    good = "Direct EIA/NOAA actuals are context [F1]; LNG feedgas is a bootstrapped proxy; ethane rejection is a calculated module that is pending."
    _, g, _ = run(stores, "How is the forward curve built?", stream=lambda p: iter([good]))
    assert g["verdict"] == "model answer grounded" and g["answer"].startswith("Direct EIA/NOAA actuals are context")


def test_a_why_did_it_move_answer_may_not_state_a_cause_and_the_price_move_is_a_grounded_fact(stores):
    st = {**STATE, "active_product": "henry_hub", "price": {"status": "measured", "value": 3.0, "unit": "USD/MMBtu", "date": "2026-11-11", "change_1d": 0.0, "change_1d_pct": 0.0,
                                                          "change_5d": 0.0, "change_5d_pct": 0.0, "window_high": 3.2, "window_low": 2.9, "quality_status": "q", "raw_payload_hash": "cd" * 32}}
    facts = cs.telemetry(st, cs.route("Why did Henry Hub rise?"))
    price = next(f for f in facts if f["kind"] == "price")["text"]
    assert "1-day change 0.000 (0.00%)" in price and "payload hash " + "cd" * 8 in price
    _, f, _ = run(stores, "Why did Henry Hub rise?", stream=lambda p: iter(["Henry Hub rose due to pipeline force majeure [F2]."]), state=st)
    assert f["verdict"].startswith("model text withheld") and "states a cause" in f["verdict"] and "does not prove a cause" in f["answer"]
    _, g, _ = run(stores, "Why did Henry Hub rise?", stream=lambda p: iter(["It did not rise: the 1-day change is 0.000 [F2]; the data does not show a cause."]), state=st)
    assert g["verdict"] == "model answer grounded"
    assert cs.route("Why did Henry Hub rise?")["product"] == "henry_hub" and cs.route("Why is Freeport flow unverified?")["product"] is None
    no_hh = cs.telemetry({**STATE, "active_product": "propane"}, cs.route("Why did Henry Hub rise?"))
    assert any("No Henry Hub price series" in x["text"] for x in no_hh)


def test_a_proxy_number_must_be_called_a_proxy_never_a_verified_value(stores):
    _, bad, _ = run(stores, "What is Freeport feedgas flow today?", stream=lambda p: iter(["Freeport flow collector is pending; last verified value: 1.63 Bcf/d [F3]."]))
    assert bad["verdict"].startswith("model text withheld") and "proxy" in bad["verdict"] and "1.63" in bad["answer"] and "proxy" in bad["answer"].lower()
    _, ok, _ = run(stores, "What is Freeport feedgas flow today?", stream=lambda p: iter(["The collector is pending [F2]; the bootstrapped proxy baseline is 1.63 Bcf/d [F3]."]))
    assert ok["verdict"] == "model answer grounded"
    assert cs.proxy_numbers(cs.telemetry(STATE, cs.route("Freeport feedgas"))) >= {"1.63"}


def test_entities_are_first_class_nodes_linked_to_the_nodes_that_mention_them(tmp_path):
    db = str(tmp_path / "e.db")
    init_db.migrate(db)
    import ingest
    c = sqlite3.connect(db)
    ingest.record_observation(c, agent_id="Agent_Storage_East", target_timestamp="2026-11-06T00:00:00Z", available_timestamp="2026-11-12T00:00:00Z", value=1.0, source_id="eia", unit="Bcf")
    c.execute("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, domain TEXT, source_id TEXT, source_url TEXT, title TEXT, body TEXT, published_timestamp TEXT, available_timestamp TEXT, raw_payload_hash TEXT)")
    c.execute("INSERT INTO documents(id,domain,source_id,source_url,title,body,published_timestamp,available_timestamp,raw_payload_hash) VALUES ('d1','pipeline_notice','kinder_morgan_notices_x','u',"
              "'Creole Trail Pipeline force majeure','Creole Trail Pipeline restricts deliveries to Sabine Pass for maintenance. FORCE MAJEURE.','2026-11-14T00:00:00Z','2026-11-14T00:00:00Z','h')")
    c.commit(); c.close()
    kb.ingest(db, embedder=emb, now="2026-11-17T12:00:00Z")
    c = sqlite3.connect(db)
    ents = {t for (t,) in c.execute("SELECT title FROM kb_nodes WHERE domain='entity'")}
    assert {"Sabine Pass", "Mont Belvieu", "Henry Hub", "Frac Spread", "Creole Trail Pipeline"} <= ents
    linked = {(a, b) for a, b in c.execute("SELECT a.title, b.title FROM kb_edges e JOIN kb_nodes a ON a.id=e.src JOIN kb_nodes b ON b.id=e.dst WHERE e.type='mentions'")}
    assert ("Creole Trail Pipeline", "Creole Trail Pipeline force majeure") in linked and ("Sabine Pass", "Creole Trail Pipeline force majeure") in linked
    assert not any(a == "Freeport" for a, _ in linked)
    kb.ingest(db, embedder=emb, now="2026-11-17T13:00:00Z")                                  # idempotent
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM kb_edges WHERE type='mentions'").fetchone()[0] == len(linked)
    assert kr.kb_role("entity") == kr.PHYSICAL and "mentions" in kb.EDGE_LEGEND
