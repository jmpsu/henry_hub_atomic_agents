import os, sqlite3, sys, _scratch, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ingest, init_db  # noqa: E401
from collectors import eia_storage as e  # noqa: E402

CSV = '''﻿Energy Information Administration
"Working Gas in Underground Storage, Lower 48"
"Released: November 5, 2026 at 10:30 a.m. (eastern time) for the Week Ending October 30, 2026"
Region,Stocks in billion (Bcf),,,,,,,,,,,,Historical Comparisons
,30-Oct-26,,,23-Oct-26,,,net change (Bcf)
East,"926","","","913","",,"13"
Midwest,"1,111","","","1,088","",,"23"
Mountain,"260","","","258","",,"2"
Pacific,"296","","","297","",,"-1"
South Central,"1,208","","","1,168","",,"40"
  Salt,"296","","","274","",,"22"
  Nonsalt,"912","","","894","",,"18"
Total,"3,801","","","3,724","",,"77"
'''
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch.TemporaryDirectory(); db = os.path.join(self.tmp.name, "t.db"); init_db.migrate(db)
        ingest.RAW_DIR = Path(self.tmp.name) / "raw"; self.conn = sqlite3.connect(db)
    def tearDown(self): self.conn.close(); self.tmp.cleanup()
    def fk(self, t, s=200): return lambda u: (s, t.encode(), "text/csv")

    def test_parse_values_and_release_time_utc(self):
        p = e.parse(CSV)
        self.assertEqual(p["values"]["Midwest"], (1111.0, 1088.0))
        self.assertEqual(p["released"].isoformat(), "2026-11-05T15:30:00+00:00")  # 10:30 EST = 15:30Z

    def test_six_agents_available_at_release_not_retrieval(self):
        out = e.collect(self.conn, self.fk(CSV), now=NOW)
        self.assertEqual(len(out), 6)
        rows = self.conn.execute("select distinct available_timestamp from pit_market_data").fetchall()
        self.assertEqual(rows, [("2026-11-05T15:30:00Z",)])
        self.assertEqual(self.conn.execute("select count(*) from pit_market_data").fetchone()[0], 6)  # prior week not fabricated

    def test_no_lookahead_before_release(self):
        e.collect(self.conn, self.fk(CSV), now=NOW)
        self.assertEqual(ingest.pit_snapshot(self.conn, "2026-11-05T15:29:59Z"), [])
        self.assertEqual(len(ingest.pit_snapshot(self.conn, "2026-11-05T15:30:00Z")), 6)

    def test_rerun_idempotent(self):
        e.collect(self.conn, self.fk(CSV), now=NOW); e.collect(self.conn, self.fk(CSV), now=NOW)
        self.assertEqual(self.conn.execute("select count(*) from pit_market_data").fetchone()[0], 6)

    def test_layout_change_rejected(self):
        with self.assertRaises(ValueError): e.parse("nope")
        with self.assertRaises(ValueError): e.parse(CSV.replace("Pacific", "Pacifc"))


if __name__ == "__main__":
    unittest.main()
