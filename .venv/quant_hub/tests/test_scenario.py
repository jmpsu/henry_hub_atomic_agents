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
