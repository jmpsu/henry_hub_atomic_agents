import io, json, sqlite3, sys, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import init_db
from collectors import eia_ng_monthly as m

def zipbody(ind=700000, res=100000, com=150000):
    rows = [{"series_id": "NG.N3035US2.M", "units": "Million Cubic Feet", "f": "M", "data": [["202608", ind], ["202607", 690846]]},
            {"series_id": "NG.N3010US2.M", "units": "Million Cubic Feet", "f": "M", "data": [["202608", res], ["202607", 110798]]},
            {"series_id": "NG.N3020US2.M", "units": "Million Cubic Feet", "f": "M", "data": [["202608", com], ["202607", 154182]]}]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z: z.writestr("NG.txt", "\n".join(json.dumps(r) for r in rows))
    return b.getvalue()

class T(unittest.TestCase):
    def conn(self):
        import tempfile, os; f = os.path.join(tempfile.mkdtemp(), "t.db"); init_db.migrate(f); return sqlite3.connect(f)
    def test_release_and_units(self):
        self.assertEqual(m.release_ts("202608"), "2026-10-31T16:00:00Z"); self.assertEqual(m.release_ts("202511"), "2026-01-31T16:00:00Z")
        self.assertAlmostEqual(m.bcfd("202608", 31000), 1.0)
    def test_load_and_revision_vintage(self):
        c = self.conn()
        r = m.collect(c, fetcher=lambda u: (200, zipbody(), "application/zip"))
        self.assertEqual({x["agent"]: x["observations_new"] for x in r}, {"Agent_Demand_Industrial": 2, "Agent_Demand_ResComm": 2})
        rc = dict(c.execute("select target_timestamp,value from pit_market_data where agent_id='Agent_Demand_ResComm'").fetchall())
        self.assertAlmostEqual(rc["2026-08-01T00:00:00Z"], (100000 + 150000) / 1000 / 31, places=3)
        r2 = m.collect(c, fetcher=lambda u: (200, zipbody(ind=710000), "application/zip"))   # revision -> new vintage only for industrial
        self.assertEqual(r2[0]["observations_new"], 1); self.assertEqual(r2[1]["observations_new"], 0)
        v = c.execute("select count(*) from pit_market_data where agent_id='Agent_Demand_Industrial' and target_timestamp='2026-08-01T00:00:00Z'").fetchone()[0]
        self.assertEqual(v, 2)
    def test_missing_series_raises(self):
        with self.assertRaises(ValueError): m.parse(zipbody()[:0] or self._without())
    def _without(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z: z.writestr("NG.txt", json.dumps({"series_id": "NG.N3035US2.M", "units": "Million Cubic Feet", "f": "M", "data": []}))
        return b.getvalue()
if __name__ == "__main__": unittest.main()
