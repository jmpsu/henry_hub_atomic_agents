import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scenario as s
A="2026-01-01T00:00:00Z"
class T(unittest.TestCase):
    def test_feedgas_drop_loosens(self):
        self.assertEqual(s.estimate_delta("Run a PIT stress test on Sabine Pass feedgas dropping 1.5 Bcf/d.")["value"], 1.5)
    def test_production_drop_tightens(self):
        self.assertEqual(s.estimate_delta("Permian production falls 2 Bcf/d")["value"], -2.0)
    def test_ambiguous_zero(self):
        self.assertEqual(s.estimate_delta("what happens with 1 Bcf/d")["value"], 0.0)
        self.assertEqual(s.estimate_delta("storage outlook")["value"], 0.0)
    def test_sql_validation(self):
        ok=f"SELECT agent_id,value FROM pit_market_data WHERE available_timestamp <= '{A}' LIMIT 5"
        self.assertIsNone(s.validate_sql(ok,A))
        for bad in ["DELETE FROM pit_market_data", ok+"; DROP TABLE x", "SELECT * FROM pit_market_data",
                    ok.replace("pit_market_data","sqlite_master"), ok+" UNION SELECT 1"]:
            self.assertIsNotNone(s.validate_sql(bad,A), bad)
    def test_fallback_valid(self):
        self.assertIsNone(s.validate_sql(s.fallback_sql(A,"Storage"),A))
if __name__=="__main__": unittest.main()

import os, sqlite3, tempfile
import init_db
class Sandbox(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "t.db"); init_db.migrate(self.db)
        c = sqlite3.connect(self.db)
        c.executemany("INSERT INTO pit_market_data (agent_id,target_timestamp,available_timestamp,value) VALUES (?,?,?,?)",
                      [("A","2026-01-01T00:00:00Z","2026-01-01T12:00:00Z",1.0), ("A","2026-01-02T00:00:00Z","2026-01-09T12:00:00Z",2.0)]); c.commit()
    def test_norm_ts(self):
        self.assertEqual(s.norm_ts("2026-01-10T23:00:00-05:00"), "2026-01-11T04:00:00Z")
        self.assertEqual(s.norm_ts("2026-01-10T00:00:00+00:00"), "2026-01-10T00:00:00Z")
        for bad in ("zzz", "2026-01-01' OR '1'='1", ""):
            with self.assertRaises(ValueError): s.norm_ts(bad)
    def test_cutoff_holds_even_with_or_true(self):
        A2 = "2026-01-05T00:00:00Z"
        rows = s.run_sandboxed(self.db, "SELECT value FROM pit_market_data WHERE available_timestamp <= 'x' OR 1=1", A2)
        self.assertEqual(rows, [(1.0,)])
    def test_other_tables_denied(self):
        A2 = "2026-01-05T00:00:00Z"
        for q in ("SELECT sql FROM sqlite_master", "SELECT count(*) FROM raw_payloads", "SELECT count(*) FROM main.pit_market_data",
                  "SELECT (SELECT count(*) FROM main.pit_market_data) FROM pit_market_data"):
            with self.assertRaises(sqlite3.DatabaseError): s.run_sandboxed(self.db, q, A2)
    def test_textual_validator_rejects_bypasses(self):
        ok = f"SELECT agent_id,value FROM pit_market_data WHERE available_timestamp <= '{A}'"
        for bad in (ok + " OR 1=1", f"SELECT (SELECT group_concat(sql) FROM sqlite_master) FROM pit_market_data WHERE available_timestamp <= '{A}'",
                    f"SELECT 1 FROM pit_market_data, raw_payloads WHERE available_timestamp <= '{A}'", "WITH x AS (SELECT 1) " + ok):
            self.assertIsNotNone(s.validate_sql(bad, A), bad)
    def test_unnormalised_as_of_refused(self):
        with self.assertRaises(ValueError): s.run_sandboxed(self.db, "SELECT 1 FROM pit_market_data", "2026-01-05' --")
