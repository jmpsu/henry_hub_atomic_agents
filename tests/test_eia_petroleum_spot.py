import os, sqlite3, sys, _scratch, unittest
from datetime import date, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import init_db
from collectors import eia_petroleum_spot as m

class T(unittest.TestCase):
    def conn(self):
        f = os.path.join(_scratch.mkdtemp(), "t.db"); init_db.migrate(f); return sqlite3.connect(f)
    def test_propane_converted_to_cents_and_available_at_close(self):
        c = self.conn()
        n = m.load(c, "EER_EPLLPA_PF4_Y44MB_DPGd", [(date(2026, 11, 10), 1.05), (date(2026, 11, 11), 1.061)], "h", "2026-11-12T10:00:00Z", "u")
        self.assertEqual(n, 2)
        r = c.execute("select value,unit,available_timestamp,provenance from pit_market_data where target_timestamp like '2026-11-11%'").fetchone()
        self.assertEqual(r, (106.1, "cents/gal", "2026-11-11T21:00:00Z", "measured"))
    def test_rerun_idempotent_and_correction_is_new_vintage(self):
        c = self.conn()
        m.load(c, "RWTCd", [(date(2026, 11, 11), 89.62)], "h", "2026-11-12T10:00:00Z", "u")
        self.assertEqual(m.load(c, "RWTCd", [(date(2026, 11, 11), 89.62)], "h", "2026-11-13T10:00:00Z", "u"), 0)
        self.assertEqual(m.load(c, "RWTCd", [(date(2026, 11, 11), 89.7)], "h", "2026-11-14T10:00:00Z", "u"), 1)
        rows = c.execute("select available_timestamp,value,quality_status from pit_market_data order by 1").fetchall()
        self.assertEqual(rows[-1], ("2026-11-14T10:00:00Z", 89.7, "revision_vintage"))
    def test_absurd_price_rejected(self):
        with self.assertRaises(ValueError): m.load(self.conn(), "RWTCd", [(date(2026, 11, 11), 9000.0)], "h", "2026-11-12T10:00:00Z", "u")
if __name__ == "__main__": unittest.main()
