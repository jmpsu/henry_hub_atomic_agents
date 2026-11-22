from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import init_db
import ingest
import kb_ingest


def _observation(conn, available, value):
    assert ingest.record_observation(
        conn, agent_id="Agent_HH_Spot_EIA", target_timestamp="2026-01-01T00:00:00Z",
        available_timestamp=available, value=value, source_id="eia_dnav_ng",
        unit="USD/MMBtu", series_id="HH")


def test_pit_revision_ledger_tracks_inserts(tmp_path):
    db = tmp_path / "ledger.db"
    init_db.migrate(str(db))
    conn = sqlite3.connect(db)
    _observation(conn, "2026-01-02T00:00:00Z", 3.0)
    _observation(conn, "2026-01-03T00:00:00Z", 4.0)
    conn.commit()
    revisions = [r[0] for r in conn.execute("SELECT recorded_revision FROM pit_revision_history ORDER BY recorded_revision")]
    assert len(revisions) == 2
    first = ingest.pit_snapshot_at_revision(conn, "2026-01-04T00:00:00Z", revisions[0])
    second = ingest.pit_snapshot_at_revision(conn, "2026-01-04T00:00:00Z", revisions[1])
    current = ingest.pit_snapshot(conn, "2026-01-04T00:00:00Z")
    assert [r[3] for r in first] == [3.0]
    assert [r[3] for r in second] == [4.0]
    assert [r[3] for r in current] == [4.0]


def test_bounded_graph_traversal_is_pit_and_cycle_safe(tmp_path):
    conn = sqlite3.connect(tmp_path / "graph.db")
    kb_ingest.ensure(conn)
    for nid, epoch in (("A", 100), ("B", 200), ("C", 300)):
        conn.execute("INSERT INTO kb_nodes(id,domain,title,available_timestamp,available_epoch) VALUES(?,?,?,?,?)",
                     (nid, "test", nid, f"2026-01-0{epoch // 100}T00:00:00Z", epoch))
    for src, dst in (("A", "B"), ("B", "C"), ("C", "A")):
        conn.execute("INSERT INTO kb_edges(src,dst,type,weight) VALUES(?,?,?,?)", (src, dst, "part_of", None))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM kb_edge_versions").fetchone()[0] == 3

    partial = kb_ingest.graph_reachable(conn, ["A"], 250, max_hops=5)
    assert {n["id"] for n in partial["nodes"]} == {"A", "B"}

    full = kb_ingest.graph_reachable(conn, ["A"], 350, max_hops=5, limit=10)
    assert {n["id"] for n in full["nodes"]} == {"A", "B", "C"}
    assert full["depths"]["C"] == 2

    one_hop = kb_ingest.graph_reachable(conn, ["A"], 350, max_hops=1)
    assert {n["id"] for n in one_hop["nodes"]} == {"A", "B"}
    assert [(l["source"], l["target"]) for l in one_hop["links"]] == [("A", "B")]
