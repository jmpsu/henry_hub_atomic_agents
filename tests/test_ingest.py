import json
import os
import sqlite3
import sys
import _scratch
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ingest  # noqa: E402
import init_db  # noqa: E402


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _scratch.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        init_db.migrate(self.db)
        ingest.RAW_DIR = Path(self.tmp.name) / "raw"
        self.conn = sqlite3.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def put(self, v, avail, target="2026-01-02T00:00:00Z", **kw):
        return ingest.record_observation(self.conn, agent_id="Agent_Storage_East", target_timestamp=target,
                                         available_timestamp=avail, value=v, source_id="eia", **kw)

    def test_revision_is_new_vintage_not_overwrite(self):
        self.assertTrue(self.put(410.0, "2026-01-08T15:30:00Z"))
        self.assertTrue(self.put(412.0, "2026-01-15T15:30:00Z"))
        n = self.conn.execute("select count(*) from pit_market_data").fetchone()[0]
        self.assertEqual(n, 2)

    def test_pit_snapshot_hides_future_revision(self):
        self.put(410.0, "2026-01-08T15:30:00Z")
        self.put(412.0, "2026-01-15T15:30:00Z")
        early = ingest.pit_snapshot(self.conn, "2026-01-10T00:00:00Z")
        late = ingest.pit_snapshot(self.conn, "2026-01-20T00:00:00Z")
        self.assertEqual([r[3] for r in early], [410.0])
        self.assertEqual([r[3] for r in late], [412.0])
        self.assertEqual(ingest.pit_snapshot(self.conn, "2026-01-01T00:00:00Z"), [])

    def test_idempotent_rerun(self):
        self.assertTrue(self.put(410.0, "2026-01-08T15:30:00Z"))
        self.assertFalse(self.put(410.0, "2026-01-08T15:30:00Z"))

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            self.put(1.0, "2026-01-08T15:30:00")

    def test_synthetic_excluded_from_measured_snapshot(self):
        self.put(410.0, "2026-01-08T15:30:00Z")
        self.put(999.0, "2026-01-08T16:30:00Z", target="2026-01-03T00:00:00Z", provenance="synthetic_scenario")
        self.assertEqual(len(ingest.pit_snapshot(self.conn, "2026-02-01T00:00:00Z")), 1)
        self.assertEqual(len(ingest.pit_snapshot(self.conn, "2026-02-01T00:00:00Z", measured_only=False)), 2)

    def test_raw_payload_archived_by_hash(self):
        h = ingest.archive_payload(self.conn, b"<html>x</html>", "eia", "http://x", 200, "2026-01-08T15:30:00Z")
        self.assertTrue((ingest.RAW_DIR / h).exists())
        h2 = ingest.archive_payload(self.conn, b"<html>x</html>", "eia", "http://x", 200, "2026-01-08T15:30:00Z")
        self.assertEqual(h, h2)

    def test_roster_has_81_unique_agents(self):
        roster = json.load(open(ROOT / "agents_roster.json"))
        ids = [r["agent_id"] for r in roster]
        self.assertEqual(len(ids), 81)
        self.assertEqual(len(set(ids)), 81)
        self.assertTrue(all(r["source"] for r in roster))


if __name__ == "__main__":
    unittest.main()
