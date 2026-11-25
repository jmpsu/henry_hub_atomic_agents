"""Live integration with the local Ollama daemon (no mocks): the configured models are installed, embeddings are real vectors,
schema-constrained extraction works on a real pipeline notice, and an agent run through the real layer logs model calls.
These tests FAIL (they do not skip) when Ollama or a configured model is missing: the platform requires them."""
import os, sqlite3, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.environ["NOTIFY"] = "0"
import numpy as np
import _scratch
import init_db, kb_ingest
from agents import llm as llm_mod, memory, workers

NOTICE = ("TENNESSEE GAS PIPELINE COMPANY, L.L.C. (TGP) critical notice 405742. Type: CAPACITY CONSTRAINT; subtype: RESTRICTIONS. "
          "Subject: RESTRICTIONS FOR 11-13-2026 ID2. Due to an unplanned outage at Station 860, TGP will restrict firm capacity through "
          "Station 860 for gas day 11-13-2026.")


class Live(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = llm_mod.status()
        d = _scratch.mkdtemp(); cls.db = os.path.join(d, "live.db"); init_db.migrate(cls.db)
        cls.conn = sqlite3.connect(cls.db); memory.ensure(cls.conn)

    def test_models_installed(self):
        self.assertTrue(self.st["daemon"], self.st); self.assertEqual(self.st["missing"], [], self.st)

    def test_real_embedding(self):
        m = llm_mod.LLM(self.conn, "live_test")
        a, b, c = (np.asarray(m.embed(t)) for t in ("pipeline force majeure compressor outage", "compressor station outage on a gas pipeline",
                                                     "propane export demand at Mont Belvieu"))
        self.assertGreaterEqual(len(a), 256)
        cos = lambda x, y: float(x @ y / np.linalg.norm(x) / np.linalg.norm(y))
        self.assertGreater(cos(a, b), cos(a, c))                                    # semantically closer text scores higher

    def test_real_structured_extraction(self):
        m = llm_mod.LLM(self.conn, "live_test")
        out = m.json("extract", "Extract the event from this pipeline notice. Use only what it says.\nNOTICE:\n" + NOTICE,
                     workers.NoticeAnalystAgent.SCHEMA, version="live-test")
        self.assertEqual(m.last_source, "model")
        self.assertIn(out["event_type"], workers.NoticeAnalystAgent.SCHEMA["properties"]["event_type"]["enum"])
        self.assertIn(out["severity"], ("low", "medium", "high"))
        row = self.conn.execute("SELECT model, ok, fallback, prompt_version FROM llm_calls WHERE task='extract' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row, (llm_mod.CODER_MODEL, 1, 0, "live-test"))

    def test_real_agent_run_extracts_notice(self):
        c = self.conn
        c.execute("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, domain TEXT, source_id TEXT, source_url TEXT, title TEXT, body TEXT, "
                  "published_timestamp TEXT, available_timestamp TEXT, retrieved_timestamp TEXT, raw_payload_hash TEXT, extraction_version TEXT, provenance TEXT)")
        c.execute("INSERT OR IGNORE INTO documents VALUES ('km_TGP_405742','pipeline_notice','kinder_morgan_notices_tgp','u','TGP restrictions',?, "
                  "'2026-11-13T12:00:00Z','2026-11-13T12:00:00Z','2026-11-13T12:05:00Z','','x','source_document')", (NOTICE,))
        c.commit()
        res = workers.NoticeAnalystAgent(5).run(c, llm_mod.LLM(c, "notice_analyst"), "2026-11-14T00:00:00Z")
        self.assertEqual(res["extracted"], 1); self.assertEqual(res["by_source"].get("model"), 1)
        et, sev, model = c.execute("SELECT event_type, severity, model FROM notice_extractions WHERE document_id='km_TGP_405742'").fetchone()
        self.assertEqual(et, "capacity_restriction")                                # source label
        self.assertEqual(model, llm_mod.CODER_MODEL)
        self.assertIn(sev, ("medium", "high"))


if __name__ == "__main__":
    unittest.main()
