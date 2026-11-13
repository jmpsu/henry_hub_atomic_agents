import io, json, os, sqlite3, sys, _scratch, unittest, zipfile
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import init_db
from collectors import steo_production as m

def body(mc=27.0, fut=99.0):
    rows = []
    for sid in {s for v in m.AGENTS.values() for s in v}:
        v = mc if sid.endswith("SNGPRMC.M") else 5.0
        rows.append({"series_id": sid, "units": "billion cubic feet per day", "f": "M",
                     "data": [["202612", fut], ["202611", fut], ["202610", v], ["202609", v]]})
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z: z.writestr("STEO.txt", "\n".join(json.dumps(r) for r in rows))
    return b.getvalue()

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
class T(unittest.TestCase):
    def conn(self):
        f = os.path.join(_scratch.mkdtemp(), "t.db"); init_db.migrate(f); return sqlite3.connect(f)
    def test_release_rule(self):
        self.assertEqual(m.release_ts("202610"), "2026-11-15T17:00:00Z"); self.assertEqual(m.release_ts("202612"), "2027-01-15T17:00:00Z")
    def test_history_only_no_forecast_months_and_sum(self):
        c = self.conn(); r = {x["agent"]: x["observations_new"] for x in m.collect(c, fetcher=lambda u: (200, body(), "z"), now=NOW)}
        self.assertEqual(r["Agent_Prod_Appalachia"], 2)
        self.assertEqual(c.execute("select count(*) from pit_market_data where target_timestamp >= '2026-11-01'").fetchone()[0], 0)
        self.assertEqual(c.execute("select value from pit_market_data where agent_id='Agent_Prod_Appalachia' and target_timestamp like '2026-10%'").fetchone()[0], 32.0)
        self.assertEqual(c.execute("select max(value) from pit_market_data").fetchone()[0], 32.0)   # the 99.0 forecast never stored
    def test_not_yet_released_month_waits(self):
        c = self.conn(); m.collect(c, fetcher=lambda u: (200, body(), "z"), now=datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertEqual(c.execute("select count(*) from pit_market_data where target_timestamp like '2026-10%'").fetchone()[0], 0)
    def test_revision_is_new_vintage(self):
        c = self.conn(); m.collect(c, fetcher=lambda u: (200, body(), "z"), now=NOW)
        r = m.collect(c, fetcher=lambda u: (200, body(mc=28.0, fut=6.0), "z"), now=datetime(2026, 12, 20, tzinfo=timezone.utc))
        self.assertEqual({x["agent"]: x["observations_new"] for x in r}["Agent_Prod_Appalachia"], 3)  # 2 revised + new Nov month
        self.assertEqual(c.execute("select count(*) from pit_market_data where agent_id='Agent_Prod_Appalachia' and target_timestamp like '2026-10%'").fetchone()[0], 2)
if __name__ == "__main__": unittest.main()
