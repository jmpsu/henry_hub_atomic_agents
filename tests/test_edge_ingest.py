import base64, json, os, shutil, sqlite3, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db

D = _scratch.TemporaryDirectory()
DB = os.path.join(D.name, "t.db"); init_db.migrate(DB)
os.environ["DB_PATH"] = DB
os.environ["RAW_DIR"] = os.path.join(D.name, "raw")
import command_hub  # noqa: E402  (imports after DB_PATH is set; the module refuses to start without it)
from fastapi.testclient import TestClient  # noqa: E402



class EdgeIngest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        D.cleanup()
    def setUp(self):
        self.c = TestClient(command_hub.app)
        self.url = command_hub._edge_sources(2026)["eia_storage"][0]
    def post(self, **kw):
        body = {"key": "eia_storage", "url": self.url, "status": 200, "content_type": "text/csv", "retrieved_timestamp": "2026-11-13T19:00:00Z",
                "headers": {"Content-Type": "text/csv", "Last-Modified": "x"}, "body_b64": base64.b64encode(b"not,a,storage,report\n").decode()}
        body.update(kw)
        return self.c.post("/ingest/edge", json=body)
    def test_whitelist(self):
        self.assertEqual(self.post(key="evil").status_code, 422)
        self.assertEqual(self.post(url="https://attacker.example/x.csv").status_code, 422)     # right key, wrong URL
        self.assertEqual(self.post(body_b64="%%%").status_code, 422)
        self.assertEqual(self.post(retrieved_timestamp="yesterday").status_code, 422)
    def test_metadata_recorded_even_when_parsing_fails(self):
        r = self.post()
        self.assertEqual(r.status_code, 200); self.assertFalse(r.json()["ok"])                 # layout check rejects the junk CSV
        c = sqlite3.connect(DB)
        row = c.execute("SELECT key, http_status, byte_length, ok, headers FROM edge_fetches ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[:4], ("eia_storage", 200, 21, 0)); self.assertIn("last-modified", json.loads(row[4]))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM pit_market_data").fetchone()[0], 0)   # nothing ingested from a bad payload
    def test_non_200_edge_fetch_is_recorded_not_parsed(self):
        r = self.post(status=503)
        self.assertEqual(r.status_code, 200); self.assertIn("HTTP 503", r.json()["result"]["error"])


if __name__ == "__main__":
    unittest.main()
