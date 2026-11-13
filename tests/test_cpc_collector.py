import os
import sqlite3
import sys
import _scratch
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ingest  # noqa: E402
import init_db  # noqa: E402
from collectors import cpc_degree_days as c  # noqa: E402

FILE = "Product: Daily Heating Degree Days\nRegion|20260101|20260102|20260103\n1|41|47|45\nCONUS|29|28|27\n"
T1 = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 11, 12, tzinfo=timezone.utc)


class CpcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "t.db")
        init_db.migrate(db)
        ingest.RAW_DIR = Path(self.tmp.name) / "raw"
        self.conn = sqlite3.connect(db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def fake(self, text, status=200):
        return lambda url: (status, text.encode(), "text/plain")

    def test_parse_conus_row(self):
        self.assertEqual(c.parse(FILE), {"2026-01-01": 29.0, "2026-01-02": 28.0, "2026-01-03": 27.0})

    def test_layout_change_rejected(self):
        with self.assertRaises(ValueError):
            c.parse("garbage")

    def test_available_at_retrieval_not_target_date(self):
        c.collect(self.conn, "Heating", 2026, self.fake(FILE), now=T1)
        row = self.conn.execute("select target_timestamp, available_timestamp, provenance from pit_market_data limit 1").fetchone()
        self.assertEqual(row[1], "2026-01-10T12:00:00Z")
        self.assertEqual(row[2], "measured")

    def test_rerun_same_data_adds_nothing_revision_adds_vintage(self):
        self.assertEqual(c.collect(self.conn, "Heating", 2026, self.fake(FILE), now=T1)["observations_new"], 3)
        self.assertEqual(c.collect(self.conn, "Heating", 2026, self.fake(FILE), now=T2)["observations_new"], 0)
        revised = FILE.replace("CONUS|29|28|27", "CONUS|30|28|27")
        self.assertEqual(c.collect(self.conn, "Heating", 2026, self.fake(revised), now=datetime(2026, 1, 12, tzinfo=timezone.utc))["observations_new"], 1)
        early = ingest.pit_snapshot(self.conn, "2026-01-11T00:00:00Z", ["Agent_Weather_Actual_HDD"])
        late = ingest.pit_snapshot(self.conn, "2026-01-13T00:00:00Z", ["Agent_Weather_Actual_HDD"])
        self.assertEqual(sorted(r[3] for r in early), [27.0, 28.0, 29.0])
        self.assertEqual(sorted(r[3] for r in late), [27.0, 28.0, 30.0])

    def test_http_error_raises(self):
        with self.assertRaises(RuntimeError):
            c.collect(self.conn, "Heating", 2026, self.fake("", 404), now=T1)


if __name__ == "__main__":
    unittest.main()
