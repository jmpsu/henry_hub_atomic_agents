import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
import init_db  # noqa: E402
import ingestion.http_client as hc  # noqa: E402


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_init_db_creates_chat_log(tmp_path):
    db = tmp_path / "pit.db"
    init_db.migrate(str(db))
    c = sqlite3.connect(db)
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(chat_log)")]
        assert cols[:5] == ["id", "ts", "cutoff", "prompt", "intent"]
        assert "answer" in cols and "total_ms" in cols
    finally:
        c.close()


def test_init_db_configures_sqlite_for_wal_and_large_cache(tmp_path):
    db = tmp_path / "pit.db"
    init_db.migrate(str(db))
    c = sqlite3.connect(db)
    try:
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        init_db.configure(c)
        assert c.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert c.execute("PRAGMA cache_size").fetchone()[0] == -2000000
        assert c.execute("PRAGMA mmap_size").fetchone()[0] >= 1_000_000_000
    finally:
        c.close()


def test_migration_runner_applies_and_checks_audit_fix(tmp_path):
    db = tmp_path / "pit.db"
    init_db.migrate(str(db))
    runner = Path(__file__).resolve().parent.parent / "migrations" / "migrate.py"
    subprocess.run([sys.executable, str(runner), "--db", str(db)], check=True, capture_output=True, text=True)
    c = sqlite3.connect(db)
    try:
        versions = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
        assert versions == {"0001", "0002", "0003", "0004", "0005", "0006", "0007"}
        assert c.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0] == 0
    finally:
        c.close()
    subprocess.run([sys.executable, str(runner), "--db", str(db), "--check"], check=True, capture_output=True, text=True)


def test_http_client_retries_transient_status_and_preserves_provenance():
    client = FakeClient([
        httpx.Response(503, content=b"retry", headers={"content-type": "text/plain"}),
        httpx.Response(200, content=b'{"ok": true}', headers={"content-type": "application/json"}),
    ])
    r = hc.fetch("https://example.test/data", client=client, retries=1, backoff=0,
                 sleep=lambda _: None, now="2026-11-22T01:02:03Z")
    assert r.attempts == 2 and r.ok and r.json() == {"ok": True}
    assert r.retrieved_timestamp == "2026-11-22T01:02:03Z"
    assert r.content_type == "application/json"
    assert len(client.calls) == 2


def test_http_client_raises_on_unexpected_status():
    client = FakeClient([httpx.Response(404, content=b"missing")])
    try:
        hc.fetch_json("https://example.test/missing", client=client, retries=0)
    except hc.HTTPClientError as exc:
        assert exc.status_code == 404 and exc.attempts == 1
    else:
        raise AssertionError("expected HTTPClientError")


def test_http_client_archives_the_exact_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    db = tmp_path / "pit.db"
    init_db.migrate(str(db))
    c = sqlite3.connect(db)
    body = b'{"series": []}'
    result = hc.FetchResult(200, body, "application/json", "https://example.test/data",
                            "https://example.test/data", 1, "2026-11-22T01:02:03Z")
    digest = hc.archive(c, result, "planned_gap")
    try:
        row = c.execute("SELECT source_id, source_url, http_status, retrieved_timestamp, content_type, byte_length "
                        "FROM raw_payloads WHERE raw_payload_hash=?", (digest,)).fetchone()
        assert row == ("planned_gap", "https://example.test/data", 200, "2026-11-22T01:02:03Z",
                       "application/json", len(body))
        assert ingest.read_payload(str(tmp_path / "raw" / digest)) == body
    finally:
        c.close()
