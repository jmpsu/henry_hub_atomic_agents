import importlib.util, json, os, sqlite3, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db, ingest
spec = importlib.util.spec_from_file_location("export_snapshot", ROOT / "scripts" / "export_snapshot.py")
ex = importlib.util.module_from_spec(spec); spec.loader.exec_module(ex)


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.d = _scratch.TemporaryDirectory(); self.db = os.path.join(self.d.name, "t.db"); init_db.migrate(self.db); c = sqlite3.connect(self.db)
        ingest.record_observation(c, agent_id="Agent_HH_Spot_EIA", target_timestamp="2026-01-05T00:00:00Z", available_timestamp="2026-01-05T21:00:00Z", value=3.1, source_id="t")
        ingest.record_observation(c, agent_id="Agent_HH_Spot_EIA", target_timestamp="2026-01-05T00:00:00Z", available_timestamp="2026-02-01T00:00:00Z", value=3.2, source_id="t")
        c.execute("INSERT INTO pit_market_data (agent_id,target_timestamp,available_timestamp,value,quality_status) VALUES ('Agent_HH_Cash_Midpoint','2026-01-05T00:00:00Z','2026-01-05T21:00:00Z',3.0,'unverified_seed')")
        c.commit(); c.close()
    def tearDown(self):
        self.d.cleanup()
    def test_deterministic_and_pit(self):
        out = Path(self.d.name) / "snap"
        p1 = ex.write(self.db, "2026-01-10T00:00:00Z", out); a = {f.name: f.read_bytes() for f in p1.iterdir()}
        p2 = ex.write(self.db, "2026-01-10T00:00:00Z", out); b = {f.name: f.read_bytes() for f in p2.iterdir()}
        self.assertEqual(a, b)                                                         # byte-identical re-export
        m = json.loads(a["manifest.json"])
        self.assertEqual(m["agents"]["Agent_HH_Spot_EIA"]["rows"], 1)                  # the Feb revision is after the cutoff
        self.assertIn("Agent_HH_Cash_Midpoint", m["roster_agents_without_real_data"])   # a seed row is not real data
        m2 = json.loads((ex.write(self.db, "2026-03-01T00:00:00Z", out) / "manifest.json").read_text())
        self.assertEqual(m2["agents"]["Agent_HH_Spot_EIA"]["rows"], 2)
        self.assertNotEqual(m["database_rows_sha256"], m2["database_rows_sha256"])
    def test_no_secrets_or_binary(self):
        p = ex.write(self.db, "2026-03-01T00:00:00Z", Path(self.d.name) / "snap")
        for f in p.iterdir():
            t = f.read_text()
            for bad in ("SECRET", "CF_ACCESS", "Bearer ", "TunnelSecret", "cfut_", "ghp_"):
                self.assertNotIn(bad, t)
            self.assertLess(f.stat().st_size, 5_000_000)


if __name__ == "__main__":
    unittest.main()
