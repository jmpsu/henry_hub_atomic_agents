import os, sqlite3, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db
from collectors import kinder_morgan_notices as m

SAMPLE = (ROOT / "tests" / "fixtures" / "km_eec_notices_sample.html").read_text(encoding="utf8", errors="ignore")


class T(unittest.TestCase):
    def test_parse_and_central_time(self):
        rows = m.parse(SAMPLE, "EEC")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["id"], "712573"); self.assertEqual(rows[0]["posted"], "2026-10-23T15:11:55Z")   # 10:11:55 AM CDT
        self.assertEqual(m.to_utc("01/15/2026 9:00:00AM"), "2026-01-15T15:00:00Z")                                # CST
    def test_wrong_pipeline_rejected(self):
        with self.assertRaises(ValueError): m.parse(SAMPLE, "TGP")              # page says ELBA EXPRESS
        with self.assertRaises(ValueError): m.parse("<html>TSP Name: ELBA EXPRESS</html>", "EEC")
    def test_store_once(self):
        d = _scratch.TemporaryDirectory(); db = os.path.join(d.name, "t.db"); init_db.migrate(db); c = sqlite3.connect(db)
        os.environ["RAW_DIR"] = os.path.join(d.name, "raw")
        f = lambda u: (200, SAMPLE.encode(), "text/html")
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        self.assertEqual(m.collect(c, f, now, ["EEC"])[0]["documents_new"], 4)
        self.assertEqual(m.collect(c, f, now, ["EEC"])[0]["documents_new"], 0)
        self.assertEqual(c.execute("SELECT DISTINCT domain, provenance FROM documents").fetchall(), [("pipeline_notice", "source_document")])
        d.cleanup()


if __name__ == "__main__":
    unittest.main()
