import os, sqlite3, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db
from collectors import eia_coal_rail as m

SAMPLE = (ROOT / "tests" / "fixtures" / "eia_coal_transport_table1.xlsx").read_bytes()


class T(unittest.TestCase):
    def test_parse_railroad_block_only(self):
        p = m.parse(SAMPLE)
        self.assertAlmostEqual(p[2008], 17.1094, places=3); self.assertAlmostEqual(p[2024], 20.7821, places=3)   # not the waterway/truck rows
        self.assertEqual(min(p), 2008)
    def test_availability_and_idempotence(self):
        d = _scratch.TemporaryDirectory(); db = os.path.join(d.name, "t.db"); init_db.migrate(db); c = sqlite3.connect(db)
        f = lambda u: (200, SAMPLE, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        r = m.collect(c, f, now=datetime(2025, 6, 1, tzinfo=timezone.utc))      # 2024 not yet public on this date
        self.assertEqual(c.execute("SELECT MAX(target_timestamp) FROM pit_market_data").fetchone()[0], "2023-01-01T00:00:00Z")
        m.collect(c, f, now=datetime(2026, 11, 13, tzinfo=timezone.utc))
        self.assertEqual(m.collect(c, f, now=datetime(2026, 11, 14, tzinfo=timezone.utc))[0]["observations_new"], 0)
        self.assertEqual(c.execute("SELECT available_timestamp FROM pit_market_data WHERE target_timestamp='2024-01-01T00:00:00Z'").fetchone()[0], "2025-12-31T16:00:00Z")
        d.cleanup()
    def test_layout_change_raises(self):
        import io, zipfile
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>Other table</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml", '<x><row><c r="A1" t="s"><v>0</v></c></row></x>')
        with self.assertRaises(ValueError): m.parse(b.getvalue())


if __name__ == "__main__":
    unittest.main()
