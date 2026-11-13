import os, sqlite3, sys, tempfile, unittest
from datetime import date, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest, init_db  # noqa: E401
from collectors import eia_prices as e  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); db = os.path.join(self.tmp.name, "t.db"); init_db.migrate(db)
        self.conn = sqlite3.connect(db)
    def tearDown(self): self.conn.close(); self.tmp.cleanup()
    def load(self, rows, name="RNGWHHDd"): return e.load(self.conn, name, rows, "h", "2026-11-12T00:00:00Z", "u")

    def test_available_evening_of_trade_date_no_lookahead(self):
        self.load([(date(2026, 1, 5), 3.1), (date(2026, 1, 6), 3.2)])
        self.assertEqual([r[3] for r in ingest.pit_snapshot(self.conn, "2026-01-05T20:59:59Z")], [])
        self.assertEqual([r[3] for r in ingest.pit_snapshot(self.conn, "2026-01-05T21:00:00Z")], [3.1])
        self.assertEqual(len(ingest.pit_snapshot(self.conn, "2026-01-06T21:00:00Z")), 2)

    def test_idempotent_and_correction_is_new_vintage(self):
        self.assertEqual(self.load([(date(2026, 1, 5), 3.1)]), 1)
        self.assertEqual(self.load([(date(2026, 1, 5), 3.1)]), 0)

    def test_futures_flagged_discontinued(self):
        self.load([(date(2024, 4, 5), 1.785)], "RNGC1d")
        q = self.conn.execute("select agent_id, quality_status from pit_market_data").fetchone()
        self.assertEqual(q[0], "Agent_HH_M1"); self.assertIn("discontinued", q[1])

    def test_absurd_price_rejected_by_gatekeeper(self):
        with self.assertRaises(ValueError): self.load([(date(2026, 1, 5), 3100.0)])  # cents mistaken for dollars


if __name__ == "__main__":
    unittest.main()
