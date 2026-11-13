import os, sqlite3, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db
from collectors import noaa_cpc_discussion as m

SAMPLE = (ROOT / "tests" / "fixtures" / "cpc_fxus06_sample.html").read_bytes()


class T(unittest.TestCase):
    def test_parse_issue_time_to_utc(self):
        d = m.parse(SAMPLE.decode())
        self.assertEqual(d["issued"], "2026-11-12T20:00:00Z")          # 300 PM EST
        self.assertEqual(d["period_6_10"], "NOV 18 - 22 2026"); self.assertTrue(d["body"].endswith("$$"))
    def test_store_once_and_layout_change(self):
        dd = _scratch.TemporaryDirectory(); db = os.path.join(dd.name, "t.db"); init_db.migrate(db); c = sqlite3.connect(db)
        os.environ["RAW_DIR"] = os.path.join(dd.name, "raw")
        now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        a = m.collect(c, fetcher=lambda u: (200, SAMPLE, "text/html"), now=now)
        b = m.collect(c, fetcher=lambda u: (200, SAMPLE, "text/html"), now=now)
        self.assertTrue(a["new"]); self.assertFalse(b["new"])
        row = c.execute("SELECT domain, available_timestamp, retrieved_timestamp, provenance FROM documents").fetchone()
        self.assertEqual(row, ("noaa_discussion", "2026-11-12T20:00:00Z", "2026-11-13T12:00:00Z", "source_document"))
        with self.assertRaises(ValueError): m.parse("<html><body>moved</body></html>")
        with self.assertRaises(ValueError): m.collect(c, fetcher=lambda u: (200, SAMPLE, "text/html"), now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        dd.cleanup()


if __name__ == "__main__":
    unittest.main()
