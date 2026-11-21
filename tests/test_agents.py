"""Research agents, Ollama layer and shared memory. Unit tests use a scripted stand-in for the model (FakeLLM) and a real
LLM object over a mocked HTTP transport; tests/test_ollama_live.py exercises the real local model."""
import json, os, sqlite3, sys, unittest
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.environ["NOTIFY"] = "0"
import _scratch
import init_db, ingest, kb_ingest
from agents import llm as llm_mod, memory, workers
from agents.llm import LLM, numbers_grounded


class FakeLLM:
    """Deterministic stand-in for the Ollama layer: embeds by hashing words, answers JSON from a script. A missing answer or
    an answer that is an Exception behaves like a model failure (fallback used when given, else raised)."""
    def __init__(self, answers=None, embed_ok=True):
        self.answers, self.calls, self.embed_ok, self.last_source = answers or {}, [], embed_ok, None
    def embed(self, text):
        if not self.embed_ok:
            raise RuntimeError("embedding model unavailable")
        v = [0.0] * 64
        for w in text.lower().split():
            v[sum(map(ord, w)) % 64] += 1.0
        return v
    def json(self, task, prompt, schema, fallback=None, validate=None, version=""):
        self.calls.append((task, prompt))
        a = self.answers.get(task)
        try:
            if a is None or isinstance(a, Exception):
                raise a or RuntimeError("no scripted answer")
            out = a(prompt) if callable(a) else dict(a)
            if validate and validate(out):
                raise ValueError(validate(out))
        except Exception:
            if fallback is None:
                self.last_source = None
                raise
            self.last_source = "fallback"
            return fallback()
        self.last_source = "model"
        return out


def _row(c, agent, day, value, avail=None, prov="measured", q="validated"):
    t = day.isoformat() + "T00:00:00Z"
    ingest.record_observation(c, agent_id=agent, target_timestamp=t, available_timestamp=avail or day.isoformat() + "T21:00:00Z", value=value,
                              source_id="t", raw_payload_hash="")


def db_with_data(notice_posted="2026-10-20T15:00:00Z"):
    d = _scratch.mkdtemp(); db = os.path.join(d, "t.db"); init_db.migrate(db); c = sqlite3.connect(db)
    memory.ensure(c)
    for i in range(300):
        day = date(2026, 1, 1) + timedelta(days=i)
        _row(c, "Agent_HH_Spot_EIA", day, 3.0 + 0.01 * ((i * 7) % 5) + (1.5 if i == 299 else 0))       # a large jump on the last day
    c.execute("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, domain TEXT, source_id TEXT, source_url TEXT, title TEXT, body TEXT, "
              "published_timestamp TEXT, available_timestamp TEXT, retrieved_timestamp TEXT, raw_payload_hash TEXT, extraction_version TEXT, provenance TEXT)")
    c.execute("INSERT INTO documents VALUES ('km_TGP_1','pipeline_notice','kinder_morgan_notices_tgp','u','TGP force majeure','TENNESSEE GAS PIPELINE (TGP) "
              "critical notice 1. Type: FORCE MAJEURE; subtype: FORCE MAJEURE. Subject: Station 87 compressor outage. FORCE MAJEURE.',?,?,?,'','x','source_document')",
              (notice_posted, notice_posted, notice_posted))
    c.execute("INSERT INTO documents VALUES ('km_EPNG_2','pipeline_notice','kinder_morgan_notices_epng','u','EPNG constraint','EL PASO NATURAL GAS (EPNG) "
              "critical notice 2. Type: CAPACITY CONSTRAINT; subtype: SEGMENTS. Subject: EPNG OPEN FOR CONFIRMATIONS ID2.',?,?,?,'','x','source_document')",
              (notice_posted, notice_posted, notice_posted))
    c.commit()
    kb_ingest.ensure(c)
    for nid, dom, title in (("kb_storage1", "storage", "EIA storage, week ending 2026-10-16"), ("kb_weather1", "weather", "Weather colder than normal")):
        c.execute("INSERT INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (nid, dom, dom, "2026-10-16", title, title + " body", "src", "", "2026-10-20T00:00:00Z", kb_ingest.epoch("2026-10-20T00:00:00Z"),
                   "2026-10-20T00:00:00Z", "", "extracted_estimate", nid, "x", np.asarray(FakeLLM().embed(title + " body"), dtype="float32").tobytes()))
    c.commit()
    return db, c


def synth_answer(rid="pipeline_restriction_hh", direction="up", ids=("kb_storage1", "kb_weather1", "kb_invented"), obs=("pipeline_events7", "hh"),
                 confidence="low"):
    def f(prompt):
        return {"relationship_id": rid, "direction": direction, "horizon_days": 5, "rationale": "Outage plus weather demand.",
                "contradictory_evidence": "Storage is ample.", "confidence": confidence, "observation_ids": list(obs),
                "evidence_ids": [i for i in ids if i in prompt or i == "kb_invented"]}
    return f


BASE = {"extract": {"event_type": "maintenance", "severity": "low", "location": "Station 87", "summary": "Compressor outage at Station 87."},
        "interpret": {"interpretation": "A jump like this can follow pipeline outages.", "related_domains": ["pipelines"], "evidence_ids": ["kb_storage1"]},
        "synthesize": synth_answer(), "diagnose": {"category": "network", "likely_fix": "retry"},
        "investigate": {"likely_cause": "source_publication_schedule", "explanation": "Not yet published.", "action": "monitor"}}


class Guards(unittest.TestCase):
    def test_numbers_grounded(self):
        self.assertEqual(numbers_grounded("Prices rose 3.25 after the 12 outage", "price 3.25 ... 12 units"), [])
        self.assertEqual(numbers_grounded("Expect a 0.40 rally", "no numbers here"), ["0.40"])
        self.assertEqual(numbers_grounded("two to 3 weeks", "x"), [])              # small counting numbers allowed
        self.assertEqual(numbers_grounded("WTI fell 6.72 and HH 0.220", "WTI change -6.720 ... HH change -0.220"), [])   # sign/rounding
        self.assertEqual(numbers_grounded("output 84.5 Bcf/d", "latest 84.47 Bcf/d"), [])
        self.assertEqual(numbers_grounded("output 85.1 Bcf/d", "latest 84.47 Bcf/d"), ["85.1"])


class OllamaLayer(unittest.TestCase):
    """The real LLM class over a mocked HTTP transport: config, retries, timeouts, fallback logging, model-presence check."""
    def conn(self):
        c = sqlite3.connect(":memory:"); llm_mod.ensure(c); return c

    def test_config_is_explicit_and_complete(self):
        for task in ("extract", "classify", "interpret", "investigate", "triage", "synthesize", "diagnose", "embed"):
            cfg = llm_mod.CONFIG[task]
            self.assertTrue(cfg["model"]); self.assertGreater(cfg["timeout"], 0)
        self.assertEqual(llm_mod.CONFIG["synthesize"]["model"], llm_mod.REASONING_MODEL)
        self.assertEqual(llm_mod.CONFIG["embed"]["model"], llm_mod.EMBED_MODEL)

    def test_retry_on_5xx_then_success(self):
        calls = []
        def handler(req):
            calls.append(1)
            return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"response": '{"category":"network","likely_fix":"x"}'})
        c = self.conn()
        orig = llm_mod.time.sleep; llm_mod.time.sleep = lambda s: None
        try:
            out = LLM(c, "t", httpx.Client(transport=httpx.MockTransport(handler))).json("diagnose", "p", {"required": ["category"]})
        finally:
            llm_mod.time.sleep = orig
        self.assertEqual(out["category"], "network"); self.assertEqual(len(calls), 2)
        self.assertEqual(c.execute("SELECT ok, fallback FROM llm_calls").fetchall(), [(1, 0)])

    def test_timeout_uses_fallback_and_is_logged(self):
        def handler(req):
            raise httpx.ReadTimeout("slow", request=req)
        c = self.conn(); m = LLM(c, "t", httpx.Client(transport=httpx.MockTransport(handler)))
        out = m.json("extract", "p", {"required": ["x"]}, fallback=lambda: {"x": "rules"}, version="v9")
        self.assertEqual(out, {"x": "rules"}); self.assertEqual(m.last_source, "fallback")
        ok, fb, err, ver = c.execute("SELECT ok, fallback, error, prompt_version FROM llm_calls").fetchone()
        self.assertEqual((ok, fb, ver), (0, 1, "v9")); self.assertIn("ReadTimeout", err)

    def test_invalid_output_fails_validation(self):
        h = lambda req: httpx.Response(200, json={"response": '{"severity":"catastrophic"}'})
        c = self.conn(); m = LLM(c, "t", httpx.Client(transport=httpx.MockTransport(h)))
        out = m.json("extract", "p", {"required": ["severity"]}, fallback=lambda: {"severity": "low"},
                     validate=lambda o: None if o["severity"] in ("low", "high") else "bad severity")
        self.assertEqual(out, {"severity": "low"})
        self.assertIn("bad severity", c.execute("SELECT error FROM llm_calls").fetchone()[0])

    def test_no_fallback_raises(self):
        h = lambda req: httpx.Response(200, json={"response": ""})
        with self.assertRaises(ValueError):
            LLM(self.conn(), "t", httpx.Client(transport=httpx.MockTransport(h))).json("extract", "p", {})

    def test_unavailable_model_skips_network(self):
        h = lambda req: (_ for _ in ()).throw(AssertionError("network must not be called"))
        m = LLM(self.conn(), "t", httpx.Client(transport=httpx.MockTransport(h)), available=False)
        self.assertEqual(m.json("extract", "p", {}, fallback=lambda: {"a": 1}), {"a": 1})
        with self.assertRaises(llm_mod.ModelUnavailable):
            m.embed("x")

    def test_status_requires_models_not_just_daemon(self):
        h = lambda req: httpx.Response(200, json={"models": [{"name": "nomic-embed-text:latest"}]})
        st = llm_mod.status(httpx.Client(transport=httpx.MockTransport(h)))
        self.assertTrue(st["daemon"]); self.assertFalse(st["ok"]); self.assertIn(llm_mod.REASONING_MODEL, st["missing"])
        down = llm_mod.status(httpx.Client(transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")))))
        self.assertFalse(down["daemon"]); self.assertFalse(down["ok"])


class Bus(unittest.TestCase):
    def test_publish_consume_once_per_consumer(self):
        _, c = db_with_data()
        memory.publish(c, "a", "anomaly", {"x": 1}); memory.publish(c, "a", "other", {"x": 2})
        self.assertEqual(len(memory.consume(c, "s1", ["anomaly"])), 1)
        self.assertEqual(memory.consume(c, "s1", ["anomaly"]), [])
        self.assertEqual(len(memory.consume(c, "s2", ["anomaly"])), 1)            # each consumer reads it once


class Memory(unittest.TestCase):
    def test_finding_persists_dedupes_and_links_evidence(self):
        _, c = db_with_data(); llm = FakeLLM()
        f1 = memory.add_finding(c, llm, "x", "T", "body text", "2026-10-21T00:00:00Z", ["kb_storage1", "kb_missing"])
        f2 = memory.add_finding(c, llm, "x", "T", "body text", "2026-10-21T00:00:00Z", ["kb_storage1"])
        self.assertTrue(f1["new"]); self.assertFalse(f2["new"]); self.assertEqual(f1["evidence_linked"], 1)
        self.assertEqual(c.execute("SELECT src, type FROM kb_edges WHERE dst=?", (f1["id"],)).fetchall(), [("kb_storage1", "evidence_for")])
        self.assertEqual(memory.findings(c, "2026-10-20T23:59:59Z"), [])             # PIT: not visible before it existed
        self.assertEqual(len(memory.findings(c, "2026-10-22T00:00:00Z")), 1)
        kb_ingest.rebuild_edges(c)                                                   # derived-edge rebuild keeps agent edges
        self.assertEqual(c.execute("SELECT COUNT(*) FROM kb_edges WHERE type='evidence_for'").fetchone()[0], 1)

    def test_finding_never_available_before_its_evidence(self):
        _, c = db_with_data(); llm = FakeLLM()
        f = memory.add_finding(c, llm, "x", "T", "early claim", "2026-10-19T00:00:00Z", ["kb_storage1"])   # evidence available 10-20
        self.assertEqual(c.execute("SELECT available_timestamp FROM kb_nodes WHERE id=?", (f["id"],)).fetchone()[0], "2026-10-20T00:00:00Z")

    def test_search_falls_back_to_keywords_and_stays_pit(self):
        _, c = db_with_data(); llm = FakeLLM(embed_ok=False)
        hits = memory.search(c, llm, "colder weather", "2026-10-21T00:00:00Z", 5)
        self.assertEqual(hits[0]["id"], "kb_weather1"); self.assertEqual(hits[0]["retrieval"], "keyword_fallback")
        self.assertEqual(memory.search(c, llm, "colder weather", "2026-10-19T00:00:00Z", 5), [])

    def test_embedding_backfill(self):
        _, c = db_with_data()
        f = memory.add_finding(c, FakeLLM(embed_ok=False), "x", "T", "stored without vector", "2026-10-21T00:00:00Z", [])
        self.assertFalse(f["embedded"])
        self.assertEqual(memory.backfill_embeddings(c, FakeLLM()), 1)
        self.assertIsNotNone(c.execute("SELECT embedding FROM kb_nodes WHERE id=?", (f["id"],)).fetchone()[0])


class Agents(unittest.TestCase):
    def test_full_cycle_with_scripted_model(self):
        db, c = db_with_data()
        llm = FakeLLM(dict(BASE))
        rep = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)
        a = rep["agents"]
        self.assertTrue(all(v["ok"] for v in a.values()), a)
        c2 = sqlite3.connect(db)
        ex = dict((r[0], r[1:]) for r in c2.execute("SELECT document_id, event_type, severity, grounded, checks FROM notice_extractions"))
        self.assertEqual(ex["km_TGP_1"][:3], ("force_majeure", "high", 1))          # the source's FORCE MAJEURE label overrides the model
        self.assertEqual(ex["km_EPNG_2"][0], "capacity_restriction")                # source Type: CAPACITY CONSTRAINT wins
        self.assertIn("source label", ex["km_EPNG_2"][3])
        self.assertEqual(a["notice_analyst"]["events_published"], 1)
        self.assertEqual(len(a["anomaly"]["anomalies"]), 1)                          # the planted last-day jump (PIT through 2026-10-27)
        s = a["synthesis"]
        self.assertGreaterEqual(s["messages_consumed"], 2); self.assertTrue(s["valid"], s["problems"])
        self.assertNotIn("kb_invented", {r[0] for r in c2.execute("SELECT src FROM kb_edges WHERE dst=?", (s["finding"],))})
        self.assertEqual(s["evaluation"]["status"], "not_testable")                  # no quantitative model for pipeline notices yet
        self.assertEqual(c2.execute("SELECT status FROM finding_status WHERE node_id=?", (s["finding"],)).fetchone()[0], "valid")
        memo = s["hypothesis_memo_fields"]
        for k in ("relationship", "instruments", "observations", "direction", "horizon", "markets", "assumptions", "contradictory_evidence",
                  "confidence", "backtest_method", "vector_nodes", "model_version"):
            self.assertTrue(memo[k], k)
        # a second run consumes nothing new and finds the earlier findings in memory
        rep2 = workers.run_all(db, None, "2026-10-29T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)
        self.assertEqual(rep2["agents"]["synthesis"]["messages_consumed"], 0)
        self.assertTrue(any("kb_finding_" in p for t, p in llm.calls if t == "synthesize"))

    def test_model_number_invention_is_withheld(self):
        db, c = db_with_data()
        llm = FakeLLM({**BASE, "interpret": {"interpretation": "Expect 9.99 next week.", "related_domains": [], "evidence_ids": []},
                       "synthesize": synth_answer(ids=())})
        rep = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)
        body = sqlite3.connect(db).execute("SELECT document FROM kb_nodes WHERE id=?", (rep["agents"]["anomaly"]["anomalies"][0]["finding"],)).fetchone()[0]
        self.assertIn("withheld", body); self.assertNotIn("9.99", body)
        self.assertFalse(rep["agents"]["synthesis"]["valid"])                       # no cited evidence -> rejected
        self.assertIn("no cited knowledge-library evidence", rep["agents"]["synthesis"]["problems"])

    def test_direction_must_agree_with_observations(self):
        db, c = db_with_data(notice_posted="2026-10-26T15:00:00Z")                  # force majeure within the last 7 days -> implies up
        llm = FakeLLM({**BASE, "synthesize": synth_answer(direction="down")})
        s = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)["agents"]["synthesis"]
        self.assertFalse(s["valid"]); self.assertTrue(any("contradicts the observations" in p for p in s["problems"]))
        self.assertEqual(sqlite3.connect(db).execute("SELECT status FROM finding_status WHERE node_id=?", (s["finding"],)).fetchone()[0], "rejected")
        self.assertEqual(sum(1 for t, p in llm.calls if t == "synthesize" and "TESTABLE ONLY" not in p), 2)   # one bounded retry, then rejected
        self.assertIn("REVIEW OF YOUR PREVIOUS ANSWER", [p for t, p in llm.calls if t == "synthesize"][1])

    def test_retry_with_feedback_can_correct_the_direction(self):
        db, c = db_with_data(notice_posted="2026-10-26T15:00:00Z")
        def synth(prompt):
            return synth_answer(direction="up" if "REVIEW OF YOUR PREVIOUS ANSWER" in prompt else "down")(prompt)
        s = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: FakeLLM({**BASE, "synthesize": synth}), run_backtests=False)["agents"]["synthesis"]
        self.assertTrue(s["valid"], s["problems"]); self.assertEqual(s["hypothesis"]["direction"], "up")
        self.assertEqual(s["first_attempt"]["hypothesis"]["direction"], "down")

    def test_confidence_is_capped_and_observations_must_be_cited(self):
        db, c = db_with_data()
        llm = FakeLLM({**BASE, "synthesize": synth_answer(confidence="high")})
        s = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)["agents"]["synthesis"]
        self.assertEqual(s["hypothesis"]["confidence"], "medium")                  # untestable relationship, two cited objects -> medium at most
        self.assertTrue(any("capped" in n for n in s["adjustments"]))
        db2, _ = db_with_data()
        llm2 = FakeLLM({**BASE, "synthesize": synth_answer(obs=("hh_chg20",))})
        s2 = workers.run_all(db2, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm2, run_backtests=False)["agents"]["synthesis"]
        self.assertTrue(s2["valid"])                                               # hh_chg20 is one of the relationship's observations
        llm3 = FakeLLM({**BASE, "synthesize": synth_answer(obs=())})
        s3 = workers.run_all(db_with_data()[0], None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm3, run_backtests=False)["agents"]["synthesis"]
        self.assertIn("cites none of the observations this relationship depends on", s3["problems"])

    def test_missing_observations_reject_the_relationship(self):
        db, c = db_with_data()
        llm = FakeLLM({**BASE, "synthesize": synth_answer(rid="production_hh", direction="down")})   # no basin production in this DB
        s = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)["agents"]["synthesis"]
        self.assertFalse(s["valid"]); self.assertTrue(any("observations unavailable" in p for p in s["problems"]))

    def test_deterministic_fallbacks_when_model_is_down(self):
        db, c = db_with_data()
        c.execute("CREATE TABLE IF NOT EXISTS collector_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, started TEXT, finished TEXT, ok INTEGER, "
                  "detail TEXT, code_version TEXT)")
        c.execute("INSERT INTO collector_runs(name,started,finished,ok,detail) VALUES ('eia_storage','2026-10-27T10:00:00Z','x',0,"
                  "'LookupError(\"table header not found\")')")
        c.commit()
        llm = FakeLLM({}, embed_ok=False)                                            # every model call fails
        rep = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)
        a = rep["agents"]
        self.assertTrue(a["diagnostics"]["ok"]); self.assertEqual(a["diagnostics"]["diagnoses"][0]["category"], "layout_change")
        self.assertEqual(a["diagnostics"]["diagnoses"][0]["source"], "fallback")
        self.assertEqual(a["notice_analyst"]["by_source"], {"model": 0, "fallback": 2})
        ex = dict(sqlite3.connect(db).execute("SELECT document_id, model FROM notice_extractions").fetchall())
        self.assertEqual(set(ex.values()), {"rules_v1"})
        self.assertIn("model unavailable", sqlite3.connect(db).execute(
            "SELECT document FROM kb_nodes WHERE id=?", (a["anomaly"]["anomalies"][0]["finding"],)).fetchone()[0])
        self.assertEqual(a["repair"]["proposals"][0]["action"], "code_suggestion")    # layout_change incident handed to the repair agent
        self.assertFalse(a["synthesis"]["ok"])                                        # synthesis fails closed: no model, no hypothesis

    def test_selector_agent_repair_is_a_dry_run_proposal(self):
        db, c = db_with_data()
        page = Path(_scratch.mkdtemp()) / "page.html"; page.write_text("<span class='new-px'>3.10</span>")
        rel = os.path.relpath(page, ROOT)
        memory.publish(c, "diagnostics", "incident", {"collector": "selfheal_demo", "category": "layout_change", "page_path": rel}, ref="selfheal_demo:1")
        seen = {}
        def fake_repair(agent, html, llm_callable):
            seen.update(agent=agent, html=html)
            return {"stage": "dry_run", "ok": True, "selectors_after": ["span.new-px", "span.px-now"], "validation": {"passed": True}}
        res = workers.RepairAgent(fake_repair).run(c, FakeLLM(BASE), "2026-10-28T00:00:00Z")
        self.assertEqual(seen["agent"], "Agent_SelfHeal_Demo"); self.assertIn("new-px", seen["html"])
        self.assertEqual(res["proposals"][0]["action"], "selector_proposal")
        self.assertEqual(c.execute("SELECT topic FROM agent_messages ORDER BY id DESC LIMIT 1").fetchone()[0], "repair_proposal")

    def test_repair_refuses_pages_outside_the_project(self):
        db, c = db_with_data()
        memory.publish(c, "diagnostics", "incident", {"collector": "selfheal_demo", "category": "layout_change", "page_path": "/etc/passwd"}, ref="x")
        res = workers.RepairAgent(lambda *a: self.fail("must not run")).run(c, FakeLLM(BASE), "2026-10-28T00:00:00Z")
        self.assertEqual(res["proposals"][0]["action"], "needs_page")


class DataQuality(unittest.TestCase):
    def test_stale_series_and_revision_detected(self):
        db, c = db_with_data()
        for i in range(40):                                                          # daily series that stops 20 days before the cutoff
            _row(c, "Agent_Crude_WTI_Spot", date(2026, 9, 1) + timedelta(days=i), 70 + i * 0.1)
        _row(c, "Agent_HH_Spot_EIA", date(2026, 10, 20), 4.5, avail="2026-10-26T12:00:00Z")   # revised vintage of an existing day (+40%)
        c.commit()
        issues = workers.DataQualityAgent().detect(c, "2026-10-30T00:00:00Z")
        kinds = {(i["type"], i["agent"]) for i in issues}
        self.assertIn(("stale", "Agent_Crude_WTI_Spot"), kinds)
        self.assertIn(("revision", "Agent_HH_Spot_EIA"), kinds)
        self.assertNotIn(("stale", "Agent_HH_Spot_EIA"), kinds)
        # PIT: at a cutoff before the revision vintage existed it is not reported
        self.assertNotIn(("revision", "Agent_HH_Spot_EIA"), {(i["type"], i["agent"]) for i in workers.DataQualityAgent().detect(c, "2026-10-25T00:00:00Z")})
        res = workers.DataQualityAgent().run(c, FakeLLM({"investigate": {"likely_cause": "collector_failure", "explanation": "It is 99 days old.",
                                                                          "action": "rerun_collector"}}), "2026-10-30T00:00:00Z")
        self.assertGreaterEqual(len(res["investigated"]), 2)
        self.assertTrue(all(o["source"] == "fallback" for o in res["investigated"]))   # 99 invented / cause inconsistent -> rules
        rev = next(o for o in res["investigated"] if o["type"] == "revision")
        self.assertEqual(rev["likely_cause"], "source_revision")                      # collector_failure is not a valid cause of a revision
        fact = next(i for i in issues if i["type"] == "revision")["fact"]
        self.assertIn("3.04 (available 2026-10-20T21:00:00Z) -> ", fact); self.assertIn("4.5 (available 2026-10-26T12:00:00Z)", fact)
        again = workers.DataQualityAgent().run(c, FakeLLM(BASE), "2026-10-30T00:00:00Z")
        self.assertEqual(again["new_issues"], 0)                                      # each issue is reported once

    def test_triage_uses_the_model_and_cites_source_evidence(self):
        db, c = db_with_data()
        avail = "2026-10-20T21:00:00Z"
        nid = kb_ingest.node_id("price", "monthly_Agent_HH_Spot_EIA:2026-10")
        c.execute("INSERT OR IGNORE INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (nid, "price", "monthly_Agent_HH_Spot_EIA", "2026-10", "HH spot", "3.04", "t", "Agent_HH_Spot_EIA", avail,
                   kb_ingest.epoch(avail), avail, "", "measured", "h", avail, np.zeros(8, dtype=np.float32).tobytes()))
        c.commit()
        llm = FakeLLM({"triage": {"assessment": "no_actionable_issues", "action": "none"}})
        res = workers.DataQualityAgent().run(c, llm, "2026-10-30T00:00:00Z")
        self.assertIn("triage", [task for task, _ in llm.calls])
        self.assertEqual(res["triage"]["assessment"], "no_actionable_issues")
        self.assertTrue(c.execute("SELECT 1 FROM kb_edges WHERE src=? AND type='evidence_for'", (nid,)).fetchone())


class Recheck(unittest.TestCase):
    def test_legacy_findings_are_rechecked_not_rewritten(self):
        db, c = db_with_data()
        llm = FakeLLM()
        old = memory.add_finding(c, llm, "synthesis", "Hypothesis: x", "Hypothesis (model-generated, validated): pipes raise propane Target propane up "
                                 "over 1 days. Domains: electricity, natural_gas. Rationale: r", "2026-10-21T00:00:00Z", [], kind="hypothesis")
        counts = workers.SynthesisAgent().recheck(c, "2026-10-28T00:00:00Z")
        self.assertEqual(counts, {"superseded": 1})
        st, why = c.execute("SELECT status, reason FROM finding_status WHERE node_id=?", (old["id"],)).fetchone()
        self.assertEqual(st, "superseded"); self.assertIn("not priced by any cited domain", why)
        self.assertIn("validated", c.execute("SELECT document FROM kb_nodes WHERE id=?", (old["id"],)).fetchone()[0])   # text kept for audit
        self.assertEqual(memory.findings(c, "2026-10-28T00:00:00Z", valid_only=True), [])


class Observations(unittest.TestCase):
    def test_observations_are_point_in_time(self):
        db, c = db_with_data()
        o = workers.observations(c, "2026-06-01T00:00:00Z")
        self.assertLessEqual(o["hh"]["available_timestamp"], "2026-06-01T00:00:00Z")
        self.assertEqual(o["hh"]["date"], "2026-05-31")
        self.assertNotIn("propane_wti", o)                                             # no propane/WTI in this DB: nothing invented


class Evaluation(unittest.TestCase):
    def _exp(self, c, eid, created, h=5):
        import experiments
        experiments.ensure(c)
        cfg = {"model": "hdd_anomaly", "horizon_days": h, "cost_bps": 10.0, "agent": "Agent_HH_Spot_EIA", "slippage_bps": 5.0}
        met = {"n": 36, "rmse": 0.17, "persistence_rmse": 0.19, "directional_hit_rate": 0.55, "mean_return_after_costs": 0.01}
        c.execute("INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?)", (eid, created, json.dumps(cfg), "dv", "a", "b", "2026-08..2026-10",
                                                                           json.dumps(met), "{}", 0, "rejected: dir_p=0.6"))
        c.commit()

    def test_evaluation_uses_only_experiments_known_at_the_cutoff(self):
        db, c = db_with_data()
        self._exp(c, "late", "2026-11-01T00:00:00Z")
        agent, entry = workers.SynthesisAgent(run_backtests=False), workers.CATALOG["weather_hdd_hh"]
        hyp = {"relationship_id": "weather_hdd_hh", "horizon_days": 5}
        f = memory.add_finding(c, FakeLLM(), "synthesis", "H", "hyp body", "2026-10-28T00:00:00Z", [], kind="hypothesis")
        self.assertEqual(agent.evaluate(c, FakeLLM(), hyp, entry, f["id"], "2026-10-28T00:00:00Z", None, db)["status"], "not_run")
        self._exp(c, "early", "2026-10-01T00:00:00Z")
        ev = agent.evaluate(c, FakeLLM(), hyp, entry, f["id"], "2026-10-28T00:00:00Z", None, db)
        self.assertEqual(ev["experiment"], "early")
        self.assertEqual(ev["backtest_results"]["sample"], "out_of_sample"); self.assertEqual(ev["backtest_results"]["cost_bps"], 10.0)
        self.assertEqual(c.execute("SELECT type FROM kb_edges WHERE src=? AND dst=?", (f["id"], ev["finding"])).fetchone()[0], "evaluated_by")
        self.assertEqual(c.execute("SELECT status FROM finding_status WHERE node_id=?", (f["id"],)).fetchone()[0], "evaluated")

    def test_untestable_primary_triggers_a_testable_hypothesis(self):
        db, c = db_with_data()
        def synth(prompt):
            if "TESTABLE ONLY" in prompt:
                return {**synth_answer()(prompt), "relationship_id": "production_hh", "direction": "down", "observation_ids": ["prod_chg3m"]}
            return synth_answer()(prompt)
        s = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: FakeLLM({**BASE, "synthesize": synth}), run_backtests=False)["agents"]["synthesis"]
        self.assertEqual(s["hypothesis"]["relationship_id"], "pipeline_restriction_hh")
        self.assertEqual(s["testable"]["hypothesis"]["relationship_id"], "production_hh")
        self.assertFalse(s["testable"]["valid"])                                    # no basin production in this DB -> rejected, not invented
        # a model that ignores the restriction is refused, and the primary hypothesis still stands
        s2 = workers.run_all(db_with_data()[0], None, "2026-10-28T00:00:00Z", llm_factory=lambda n: FakeLLM(dict(BASE)), run_backtests=False)["agents"]["synthesis"]
        self.assertTrue(s2["valid"]); self.assertFalse(s2["testable"]["ok"]); self.assertIn("outside", s2["testable"]["error"])


class DataQualityRecheck(unittest.TestCase):
    def test_inconsistent_cause_is_superseded_and_reinvestigated(self):
        db, c = db_with_data()
        _row(c, "Agent_HH_Spot_EIA", date(2026, 10, 20), 4.5, avail="2026-10-26T12:00:00Z"); c.commit()
        dq = workers.DataQualityAgent()
        issue = next(i for i in dq.detect(c, "2026-10-30T00:00:00Z") if i["type"] == "revision")
        f = memory.add_finding(c, FakeLLM(), "data_quality", "Data quality: revision", f"Data-quality issue (revision): {issue['fact']} Likely cause: "
                               "source_publication_schedule. Not yet published. Action: monitor.", "2026-10-29T00:00:00Z", [], "extracted_estimate", "data_quality")
        memory.publish(c, "data_quality", "data_quality", {**issue, "finding": f["id"]}, ref=issue["ref"])
        res = dq.run(c, FakeLLM(BASE), "2026-10-30T00:00:00Z")
        self.assertEqual(res["rechecked"], {"superseded": 1})
        self.assertIn(issue["ref"], {f"revision:{o['agent']}:" + issue["ref"].split(":", 2)[2] for o in res["investigated"] if o["type"] == "revision"})
        self.assertEqual(c.execute("SELECT status FROM finding_status WHERE node_id=?", (f["id"],)).fetchone()[0], "superseded")


class Circularity(unittest.TestCase):
    def test_hypothesis_citing_only_earlier_findings_is_rejected(self):
        db, c = db_with_data()
        prior = memory.add_finding(c, FakeLLM(), "synthesis", "Hypothesis: pipeline", "Relationship id: pipeline_restriction_hh earlier hypothesis.",
                                   "2026-10-21T00:00:00Z", ["kb_storage1"], kind="hypothesis")
        memory.set_status(c, prior["id"], "valid", "x", "synth-3")
        def synth(prompt):
            return {**synth_answer()(prompt), "evidence_ids": [prior["id"]]}
        llm = FakeLLM({**BASE, "synthesize": synth})
        s = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False)["agents"]["synthesis"]
        self.assertFalse(s["valid"]); self.assertTrue(any("circular" in p for p in s["problems"]))
        prompt = next(p for t, p in llm.calls if t == "synthesize")
        self.assertIn("pipeline_restriction_hh:", prompt)
        self.assertIn("observations unavailable", prompt)                         # e.g. production_hh: no basin data in this DB
        self.assertIn("testable by backtest", prompt)


class RetrievalHygiene(unittest.TestCase):
    def test_rejected_findings_are_not_offered_as_evidence(self):
        db, c = db_with_data()
        dead = memory.add_finding(c, FakeLLM(), "synthesis", "Hypothesis: storage weather pipeline", "storage weather pipeline outage hypothesis",
                                  "2026-10-21T00:00:00Z", [], kind="hypothesis")
        memory.set_status(c, dead["id"], "rejected", "direction contradicted the observations", "synth-3")
        llm = FakeLLM(dict(BASE))
        workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: llm, run_backtests=False, only=["synthesis"])
        prompts = [p for t, p in llm.calls if t == "synthesize"]
        self.assertTrue(prompts); self.assertTrue(all(dead["id"] not in p for p in prompts))


class EvaluatedHypothesisMemo(unittest.TestCase):
    def test_valid_testable_hypothesis_is_evaluated_and_memo_persisted(self):
        db, c = db_with_data()
        for i in range(20):                                                          # colder than normal: actual 20 HDD vs normal 10
            day = date(2026, 10, 8) + timedelta(days=i)
            _row(c, "Agent_Weather_Actual_HDD", day, 20.0)
            ingest.record_observation(c, agent_id="Agent_Weather_30YrNormal_HDD", target_timestamp=day.isoformat() + "T00:00:00Z",
                                      available_timestamp="2021-05-04T00:00:00Z", value=10.0, source_id="t", raw_payload_hash="",
                                      provenance="extracted_estimate", quality_status="derived_validated")
        c.commit()
        Evaluation._exp(None, c, "early", "2026-10-01T00:00:00Z", h=5)
        def synth(prompt):
            return {**synth_answer(rid="weather_hdd_hh", direction="up", obs=("hdd_anom7",))(prompt)}
        s = workers.run_all(db, None, "2026-10-28T00:00:00Z", llm_factory=lambda n: FakeLLM({**BASE, "synthesize": synth}), run_backtests=False)["agents"]["synthesis"]
        self.assertTrue(s["valid"], s["problems"])
        self.assertIn("COLDER than normal", " ".join(s["hypothesis_memo_fields"]["observations"]))
        self.assertEqual(s["evaluation"]["status"], "evaluated"); self.assertEqual(s["memo_problems"], [])
        c2 = sqlite3.connect(db)
        memo = c2.execute("SELECT document, provenance FROM kb_nodes WHERE id=?", (s["memo_finding"],)).fetchone()
        self.assertIn("MODEL-GENERATED HYPOTHESIS", memo[0]); self.assertEqual(memo[1], "model_hypothesis")
        srcs = {r[0] for r in c2.execute("SELECT src FROM kb_edges WHERE dst=? AND type='evidence_for'", (s["memo_finding"],))}
        self.assertTrue({s["finding"], s["evaluation"]["finding"]} <= srcs)


if __name__ == "__main__":
    unittest.main()
