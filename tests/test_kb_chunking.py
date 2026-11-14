"""Long source documents are chunked so their whole text is embedded and searchable, with parent-child (part_of) edges
that survive the derived-edge rebuild, and the same PIT metadata as the parent."""
import os, sqlite3, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import _scratch
import init_db, kb_ingest
from test_agents import FakeLLM

PARA = ["Paragraph %d. " % i + ("The 6-10 day outlook favors below-normal temperatures across the East. " * 12) for i in range(9)]
BODY = "\n\n".join(PARA)


class Chunking(unittest.TestCase):
    def test_chunks_cover_the_whole_text(self):
        parts = kb_ingest.chunk_text(BODY)
        self.assertGreater(len(parts), 2)
        self.assertTrue(all(len(p) <= kb_ingest.CHUNK_CHARS for p in parts))
        joined = "\n\n".join(parts)
        for p in PARA:
            self.assertIn(p.strip(), joined)                                        # nothing dropped
        long = "x" * 5000
        hard = kb_ingest.chunk_text(long)
        self.assertEqual(hard[0][-kb_ingest.CHUNK_OVERLAP:], hard[1][:kb_ingest.CHUNK_OVERLAP])   # overlap on a hard split

    def test_ingest_embeds_chunks_with_parent_edges_and_pit(self):
        d = _scratch.mkdtemp(); db = os.path.join(d, "c.db"); init_db.migrate(db); c = sqlite3.connect(db)
        c.execute("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, domain TEXT, source_id TEXT, source_url TEXT, title TEXT, body TEXT, "
                  "published_timestamp TEXT, available_timestamp TEXT, retrieved_timestamp TEXT, raw_payload_hash TEXT, extraction_version TEXT, provenance TEXT)")
        c.execute("INSERT INTO documents VALUES ('cpc_610_1','noaa_discussion','noaa_cpc_discussion','u','CPC 6-10 day discussion',?, "
                  "'2026-11-10T20:00:00Z','2026-11-10T20:00:00Z','2026-11-10T20:05:00Z','abc','x','source_document')", (BODY,))
        c.commit(); c.close()
        res = kb_ingest.ingest(db, None, FakeLLM().embed, now="2026-11-11T00:00:00Z")
        c = sqlite3.connect(db)
        parent = kb_ingest.node_id("noaa_discussion", "document_noaa_cpc_discussion:cpc_610_1")
        kids = c.execute("SELECT src FROM kb_edges WHERE dst=? AND type='part_of'", (parent,)).fetchall()
        self.assertEqual(len(kids), len(kb_ingest.chunk_text(BODY)))
        rows = c.execute("SELECT available_timestamp, raw_payload_hash, provenance, embedding IS NOT NULL FROM kb_nodes WHERE id IN (%s)"
                         % ",".join("?" * len(kids)), [k[0] for k in kids]).fetchall()
        self.assertEqual(set(rows), {("2026-11-10T20:00:00Z", "abc", "source_document", 1)})
        again = kb_ingest.ingest(db, None, FakeLLM().embed, now="2026-11-12T00:00:00Z")           # idempotent; edges kept
        self.assertEqual(again["new"], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM kb_edges WHERE type='part_of'").fetchone()[0], len(kids))
        g = kb_ingest.graph(c, kb_ingest.epoch("2026-11-09T00:00:00Z"))
        self.assertEqual(g["total_nodes"], 0)                                          # PIT: nothing before publication


if __name__ == "__main__":
    unittest.main()
