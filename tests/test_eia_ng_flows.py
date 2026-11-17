import io, json, sqlite3, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import init_db  # noqa: E402
from collectors import eia_ng_flows as f  # noqa: E402


def _zip(overrides=None, drop=None, units="Million Cubic Feet"):
    lines = ['{"category_id":"1"}']                                   # category rows have no series_id and must be ignored
    for i, (agent, sid) in enumerate(f.SERIES.items()):
        if sid == drop:
            continue
        data = [["202608", 1000.0 + i], ["202607", 900.0 + i], ["202512", 800.0 + i], ["201412", 5.0]]   # 201412 is before FIRST
        if overrides and sid in overrides:
            data = overrides[sid]
        lines.append(json.dumps({"series_id": sid, "name": agent, "units": units, "f": "M", "data": data}))
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("NG.txt", "\n".join(lines))
    return b.getvalue()


def _conn():
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    return sqlite3.connect(db)


def _fetcher(body):
    return lambda url: (200, body, "application/zip")


NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def test_thirteen_distinct_series_covering_eight_terminals_and_five_borders():
    assert len(f.SERIES) == 13 and len(set(f.SERIES.values())) == 13
    assert sum(a.startswith("Agent_LNGExports_") for a in f.SERIES) == 8 and sum(a.startswith("Agent_BorderFlow_") for a in f.SERIES) == 5


def test_collect_stores_raw_mmcf_with_release_rule_pit_and_skips_pre_2015():
    conn = _conn()
    out = f.collect(conn, fetcher=_fetcher(_zip()), now=NOW)
    assert all(r["observations_new"] == 3 for r in out)                  # 202608, 202607, 202512; 201412 excluded
    row = conn.execute("SELECT value, unit, target_timestamp, available_timestamp, source_id, quality_status, provenance, series_id FROM pit_market_data "
                       "WHERE agent_id='Agent_LNGExports_SabinePass' AND target_timestamp='2026-08-01T00:00:00Z'").fetchone()
    assert row[0] == 1000.0 and row[1] == "MMcf/month"                   # stored as published: no daily conversion
    assert row[3] == "2026-10-31T16:00:00Z"                              # Aug published at the end of Oct (M+2), never earlier
    assert row[4] == "eia_ng_bulk" and row[5] == "latest_vintage_release_rule_assumed" and row[6] == "measured" and row[7].endswith("YSPL-Z00_MMCF.M")


def test_rerun_is_idempotent_and_a_revision_becomes_a_new_vintage_at_retrieval_time():
    conn = _conn()
    f.collect(conn, fetcher=_fetcher(_zip()), now=NOW)
    assert all(r["observations_new"] == 0 for r in f.collect(conn, fetcher=_fetcher(_zip()), now=NOW))
    sid = f.SERIES["Agent_LNGExports_Cameron"]
    rev = {sid: [["202608", 4242.0], ["202607", 903.0], ["202512", 803.0]]}
    out = {r["agent"]: r for r in f.collect(conn, fetcher=_fetcher(_zip(rev)), now=datetime(2026, 12, 5, tzinfo=timezone.utc))}
    assert out["Agent_LNGExports_Cameron"]["observations_new"] == 1
    rows = conn.execute("SELECT value, available_timestamp, quality_status FROM pit_market_data WHERE agent_id='Agent_LNGExports_Cameron' "
                        "AND target_timestamp='2026-08-01T00:00:00Z' ORDER BY available_timestamp").fetchall()
    assert [r[0] for r in rows] == [1003.0, 4242.0] and rows[1][1] == "2026-12-05T00:00:00Z" and rows[1][2] == "revision_vintage"
    # a cutoff between the two vintages must still see the first value
    snap = {r[1][:7]: r[3] for r in __import__("ingest").pit_snapshot(conn, "2026-11-30T00:00:00Z", ["Agent_LNGExports_Cameron"])}
    assert snap["2026-08"] == 1003.0


def test_missing_series_and_wrong_units_fail_loudly_instead_of_writing_partial_data():
    conn = _conn()
    with pytest.raises(ValueError, match="series missing"):
        f.collect(conn, fetcher=_fetcher(_zip(drop=f.SERIES["Agent_BorderFlow_Noyes_FromCanada"])), now=NOW)
    with pytest.raises(ValueError, match="unexpected units"):
        f.collect(conn, fetcher=_fetcher(_zip(units="Dollars per Thousand Cubic Feet")), now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM pit_market_data").fetchone()[0] == 0


def test_http_error_raises():
    with pytest.raises(RuntimeError, match="HTTP 503"):
        f.collect(_conn(), fetcher=lambda u: (503, b"", ""), now=NOW)
