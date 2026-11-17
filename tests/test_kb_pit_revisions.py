"""KB-PIT-REV: a revised observation must not erase the version that was known earlier.

EIA weekly storage, six regions, target week 2026-01-02: vintage 1 available 2026-01-08T15:30Z (600 Bcf), vintage 2 available 2026-01-15T15:30Z (660 Bcf).
Every read path (graph, node_detail, search, summary) must return the vintage that was latest at the requested as_of and never one made available after it.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kb_ingest as kb  # noqa: E402

TGT = "2026-01-02T00:00:00Z"
V1, V2 = "2026-01-08T15:30:00Z", "2026-01-15T15:30:00Z"
EMB = lambda text: [1.0, 0.0, 0.0]  # noqa: E731  deterministic stub; no Ollama


def _insert(c, agent, av, val):
    c.execute("INSERT INTO pit_market_data VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (agent, TGT, av, val, "EIA_TEST", "u", av, av, None, "Bcf", "US", "s", "h" + av, "v1", "ok", "measured"))


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "t.db")
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE pit_market_data(agent_id,target_timestamp,available_timestamp,value,source_id,source_url,retrieved_timestamp,
        published_timestamp,revision_timestamp,unit,geographic_scope,series_id,raw_payload_hash,extraction_version,quality_status,provenance)""")
    for a in kb.STORAGE:
        _insert(c, a, V1, 100.0)
    c.commit()
    c.close()
    kb.ingest(path, embedder=EMB, now="2026-01-08T16:00:00Z")
    c = sqlite3.connect(path)
    for a in kb.STORAGE:
        _insert(c, a, V2, 110.0)
    c.commit()
    c.close()
    kb.ingest(path, embedder=EMB, now="2026-01-15T16:00:00Z")
    return path


def _titles(conn, t):
    return [n["title"] for n in kb.graph(conn, kb.epoch(t))["nodes"]]


def test_graph_between_vintages_returns_first_vintage(db):
    assert _titles(sqlite3.connect(db), "2026-01-09T00:00:00Z") == ["EIA storage, week ending 2026-01-02: 600 Bcf"]


def test_graph_after_revision_returns_revised_vintage_only(db):
    assert _titles(sqlite3.connect(db), "2026-01-16T00:00:00Z") == ["EIA storage, week ending 2026-01-02: 660 Bcf"]


def test_nothing_visible_before_first_availability(db):
    c = sqlite3.connect(db)
    t = kb.epoch("2026-01-05T00:00:00Z")
    assert kb.graph(c, t)["nodes"] == [] and kb.search(c, [1.0, 0, 0], t) == [] and kb.summary(c, t)["nodes"] == 0


def test_exact_cutoff_is_inclusive_and_one_second_earlier_is_not(db):
    c = sqlite3.connect(db)
    assert "660" in kb.graph(c, kb.epoch(V2))["nodes"][0]["title"]
    assert "600" in kb.graph(c, kb.epoch(V2) - 1)["nodes"][0]["title"]


def test_node_detail_search_summary_are_version_aware(db):
    c = sqlite3.connect(db)
    nid = kb.graph(c, kb.epoch(V2))["nodes"][0]["id"]
    mid = kb.epoch("2026-01-09T00:00:00Z")
    assert "600 Bcf" in kb.node_detail(c, nid, mid)["document"]
    assert "660 Bcf" in kb.node_detail(c, nid, kb.epoch("2026-01-16T00:00:00Z"))["document"]
    assert kb.node_detail(c, nid, kb.epoch("2026-01-05T00:00:00Z")) is None
    hits = kb.search(c, [1.0, 0, 0], mid)
    assert len(hits) == 1 and "600 Bcf" in hits[0]["document"]
    assert kb.summary(c, mid)["nodes"] == 1 and kb.summary(c, kb.epoch("2026-01-16T00:00:00Z"))["nodes"] == 1


def test_current_table_holds_latest_and_archive_holds_superseded(db):
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM kb_nodes WHERE domain<>'fundamentals'").fetchone()[0] == 1          # the 7 G5 element-definition nodes are a separate class
    assert c.execute("SELECT COUNT(*) FROM kb_nodes WHERE domain='fundamentals'").fetchone()[0] == 7
    assert c.execute("SELECT available_timestamp FROM kb_node_versions").fetchall() == [(V1,)]


def test_reingest_without_change_does_not_duplicate_versions(db):
    kb.ingest(db, embedder=EMB, now="2026-01-20T00:00:00Z")
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM kb_node_versions").fetchone()[0] == 1 and c.execute("SELECT COUNT(*) FROM kb_nodes WHERE domain<>'fundamentals'").fetchone()[0] == 1


def test_read_only_db_without_archive_still_reads(tmp_path):
    """The public service opens DBs written before kb_node_versions existed; reads must fall back to kb_nodes, not return empty."""
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE kb_nodes(id TEXT PRIMARY KEY, domain TEXT, series_key TEXT, period TEXT, title TEXT, document TEXT,
        source_id TEXT, agent_ids TEXT, available_timestamp TEXT, available_epoch INTEGER, published_timestamp TEXT, raw_payload_hash TEXT,
        provenance TEXT, doc_hash TEXT, created TEXT, embedding BLOB)""")
    c.execute("CREATE TABLE kb_edges(src TEXT, dst TEXT, type TEXT, weight REAL, PRIMARY KEY(src, dst, type))")
    c.execute("INSERT INTO kb_nodes VALUES ('kb_x','storage','s','2026-01-02','T','D','src','a',?,?,?,'h','extracted_estimate','dh','c',NULL)", (V1, kb.epoch(V1), V1))
    c.commit()
    c.close()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert [n["id"] for n in kb.graph(ro, kb.epoch(V2))["nodes"]] == ["kb_x"]
    assert kb.graph(ro, kb.epoch(V1) - 1)["nodes"] == [] and kb.summary(ro, kb.epoch(V2))["nodes"] == 1
    assert kb.node_detail(ro, "kb_x", kb.epoch(V2))["title"] == "T"
