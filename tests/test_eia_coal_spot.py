import json, os, sqlite3, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db
from collectors import eia_coal_spot as m

SAMPLE = (ROOT / "tests" / "fixtures" / "eia_coal_archive_sample.json").read_bytes()


class T(unittest.TestCase):
    def setUp(self):
        self.d = _scratch.TemporaryDirectory(); db = os.path.join(self.d.name, "t.db"); init_db.migrate(db); self.c = sqlite3.connect(db)
        os.environ["RAW_DIR"] = os.path.join(self.d.name, "raw")
    def tearDown(self):
        self.d.cleanup()
    def test_load_units_and_availability(self):
        r = m.collect(self.c, fetcher=lambda u: (200, SAMPLE, "application/json"), now=datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
        self.assertEqual({x["agent"]: x["observations_new"] for x in r}, {"Agent_Coal_CAPP_SpotPrice": 6, "Agent_Coal_PRB_SpotPrice": 6})
        row = self.c.execute("SELECT value, unit, available_timestamp FROM pit_market_data WHERE agent_id='Agent_Coal_PRB_SpotPrice' "
                             "AND target_timestamp='2026-11-06T00:00:00Z'").fetchone()
        self.assertEqual(row, (14.65, "USD/short ton", "2026-11-10T17:00:00Z"))          # Friday + 4 days, 17:00Z
    def test_week_not_yet_public_is_held_back(self):
        m.collect(self.c, fetcher=lambda u: (200, SAMPLE, "application/json"), now=datetime(2026, 11, 9, tzinfo=timezone.utc))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM pit_market_data WHERE target_timestamp LIKE '2026-11-06%'").fetchone()[0], 0)
    def test_layout_change_raises(self):
        with self.assertRaises(ValueError): m.parse(json.dumps({"data": [{"other": []}]}).encode())
        bad = json.loads(SAMPLE); [r.pop("POWDER_RIVER_BASIN") for r in bad["data"][0]["snl_dpst"]]
        with self.assertRaises(ValueError): m.parse(json.dumps(bad).encode())


if __name__ == "__main__":
    unittest.main()
