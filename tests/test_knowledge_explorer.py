"""Read-only knowledge explorer routes on the public markets service: graph, node inspector, agent activity, /knowledge page.
Point-in-time filtering, provenance/raw-payload traceability, and no privileged routes."""
import hashlib, os, sqlite3, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
os.environ["NOTIFY"] = "0"
import numpy as np
import _scratch
import init_db, ingest, kb_ingest
from agents import memory
from test_agents import FakeLLM

D = _scratch.mkdtemp()
DB = os.path.join(D, "k.db"); init_db.migrate(DB)
_prev = os.environ.get("DB_PATH")
os.environ["DB_PATH"] = DB
import markets_hub  # noqa: E402
markets_hub.DB_PATH = DB
if _prev is not None:
    os.environ["DB_PATH"] = _prev
from fastapi.testclient import TestClient  # noqa: E402


def seed():
    c = sqlite3.connect(DB); memory.ensure(c)
    raw = b"week,east\n2026-10-16,800\n"
    h = hashlib.sha256(raw).hexdigest()
    ingest.archive_payload(c, raw, "eia_wngsr", "https://ir.eia.gov/ngs/wngsr.csv", 200, "2026-10-16T15:31:00Z", "text/csv")
    for nid, dom, title, avail, rh in (("kb_storage1", "storage", "EIA storage week ending 2026-10-16", "2026-10-16T15:30:00Z", h),
                                       ("kb_weather1", "weather", "Weather colder than normal", "2026-10-20T00:00:00Z", "")):
        c.execute("INSERT INTO kb_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (nid, dom, dom, avail[:10], title, title + " body", "eia_wngsr", "Agent_Storage_East", avail, kb_ingest.epoch(avail), avail, rh,
                   "extracted_estimate", nid, "x", np.asarray(FakeLLM().embed(title), dtype="float32").tobytes()))
    c.commit()
    f = memory.add_finding(c, FakeLLM(), "synthesis", "Hypothesis: storage", "A storage hypothesis.", "2026-10-21T00:00:00Z",
                           ["kb_storage1", "kb_weather1"], kind="hypothesis")
    memory.set_status(c, f["id"], "valid", "passes synth-3 checks", "synth-3")
    memory.publish(c, "notice_analyst", "pipeline_event", {"x": 1}, ref="d1"); memory.consume(c, "synthesis", ["pipeline_event"])
    memory.run_record(c, "synthesis", "2026-10-21T00:00:00Z", "2026-10-21T00:00:00Z", True, {"valid": True, "hypothesis": {"relationship_id": "x"}})
    c.close()
    return f["id"], h


class Explorer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fid, cls.hash = seed()
        cls.c = TestClient(markets_hub.app)

    def test_graph_carries_agent_edges_and_verdicts(self):
        g = self.c.get("/api/knowledge-graph?as_of=2026-10-22T00:00:00Z").json()
        self.assertEqual(g["total_nodes"], 3)
        node = next(n for n in g["nodes"] if n["id"] == self.fid)
        self.assertEqual(node["status"], "valid")
        self.assertEqual({(l["source"], l["type"]) for l in g["links"] if l["target"] == self.fid}, {("kb_storage1", "evidence_for"), ("kb_weather1", "evidence_for")})
        self.assertIn("evidence_for", g["edge_legend"])

    def test_graph_is_point_in_time(self):
        g = self.c.get("/api/knowledge-graph?as_of=2026-10-18T00:00:00Z").json()
        self.assertEqual([n["id"] for n in g["nodes"]], ["kb_storage1"])

    def test_node_inspector_traces_provenance_and_payload(self):
        n = self.c.get("/api/knowledge-node/kb_storage1?as_of=2026-10-22T00:00:00Z").json()["node"]
        self.assertEqual(n["raw_payload"]["source_url"], "https://ir.eia.gov/ngs/wngsr.csv")
        self.assertEqual(n["raw_payload"]["http_status"], 200)
        self.assertNotIn("archive_path", n["raw_payload"])                          # no local filesystem paths on the public service
        self.assertIn(self.fid, {e["id"] for e in n["edges"] if e["type"] == "evidence_for" and e["direction"] == "out"})
        f = self.c.get(f"/api/knowledge-node/{self.fid}?as_of=2026-10-22T00:00:00Z").json()["node"]
        self.assertEqual(f["status"]["status"], "valid"); self.assertEqual(f["provenance"], "model_hypothesis")

    def test_node_inspector_is_pit_and_validates_ids(self):
        self.assertEqual(self.c.get(f"/api/knowledge-node/{self.fid}?as_of=2026-10-20T12:00:00Z").status_code, 404)
        self.assertEqual(self.c.get("/api/knowledge-node/kb_x;drop?as_of=2026-10-22T00:00:00Z").status_code, 422)
        # evidence edges to objects not yet available are hidden too
        n = self.c.get("/api/knowledge-node/kb_storage1?as_of=2026-10-17T00:00:00Z").json()["node"]
        self.assertEqual(n["edges"], [])

    def test_agent_activity_and_page(self):
        a = self.c.get("/api/agents/activity").json()
        self.assertEqual(a["runs"][0]["agent"], "synthesis")
        self.assertEqual(a["messages"][0]["consumed_by"], ["synthesis"])
        self.assertEqual(a["finding_status"], {"valid": 1})
        p = self.c.get("/knowledge")
        self.assertEqual(p.status_code, 200); self.assertIn("knowledge.js", p.text)
        self.assertEqual(self.c.get("/static/knowledge.js").status_code, 200)

    def test_public_service_has_no_privileged_agent_routes(self):
        for path in ("/agents/run", "/kb/ingest", "/execute", "/api/agents/run"):
            self.assertIn(self.c.post(path, json={}).status_code, (404, 405), path)

    def test_public_service_never_writes(self):
        before = hashlib.sha256(Path(DB).read_bytes()).hexdigest()
        for u in ("/api/knowledge-graph", f"/api/knowledge-node/{self.fid}", "/api/agents/activity"):
            self.c.get(u)
        self.assertEqual(hashlib.sha256(Path(DB).read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
