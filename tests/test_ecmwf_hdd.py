import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors import ecmwf_hdd as e

class T(unittest.TestCase):
    def test_index_range_inclusive_end(self):
        idx = '{"param":"msl","levtype":"sfc","_offset":0,"_length":100}\n{"param":"2t","levtype":"sfc","_offset":100,"_length":50}\n'
        self.assertEqual(e.parse_index(idx), (100, 149))
    def test_missing_param_raises(self):
        with self.assertRaises(ValueError): e.parse_index('{"param":"msl","_offset":0,"_length":1}')
    def test_verified_limit_is_step_360_so_day14_is_last_full_day_and_day15_unsupported(self):
        self.assertEqual(e.MAX_STEP, 360)
        self.assertLessEqual(24 * 14 + 6, e.MAX_STEP)     # Day 14 needs step 342: all four samples exist
        self.assertGreater(24 * 15 + 6, e.MAX_STEP)       # Day 15 needs step 366: does not exist in open data
        self.assertEqual(list(e.DAYS), list(range(1, 15)))
if __name__ == "__main__":
    unittest.main()


# ---- mirror fallback, error classification, per-day tolerance ------------------------------------------------------------------------------
import sqlite3
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import init_db  # noqa: E402

IDX = '{"param":"2t","levtype":"sfc","_offset":0,"_length":10}\n'


class R:
    def __init__(self, code, text="", content=b"GRIB", headers=None):
        self.status_code, self.text, self.content, self.headers = code, text, content, headers or {}


class FakeClient:
    """routes: substring of URL -> list of responses served in order (last one repeats); anything else 404."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, headers=None):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                r = resp.pop(0) if len(resp) > 1 else resp[0]
                return r
        return R(404)


def _db():
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    return sqlite3.connect(db)


def test_fetch_retries_a_503_then_falls_through_to_the_next_mirror():
    c = FakeClient({"data.ecmwf.int": [R(503)], "googleapis": [R(200, IDX)]})
    r, url = e.fetch(c, "20261117", 24, ".index", sleep=lambda s: None)
    assert r.status_code == 200 and "googleapis" in url
    assert sum("data.ecmwf.int" in u for u in c.calls) == 2          # retried once on the first mirror


def test_fetch_distinguishes_not_published_from_service_unavailable():
    with pytest.raises(e.NotPublished):
        e.fetch(FakeClient({}), "20261117", 24, ".index", sleep=lambda s: None)               # every mirror 404
    with pytest.raises(e.Unavailable):
        e.fetch(FakeClient({"data.ecmwf.int": [R(404)], "googleapis": [R(404)], "amazonaws": [R(503)]}), "20261117", 24, ".index", sleep=lambda s: None)


def test_collect_reports_service_unavailable_not_no_run_found():
    c = FakeClient({"": [R(503)]})
    with pytest.raises(RuntimeError) as ei:
        e.collect(_db(), now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc), client=c, sleep=lambda s: None)
    assert "service unavailable" in str(ei.value) and "no ECMWF 00z run found" not in str(ei.value)


def test_collect_uses_yesterdays_run_stores_pit_rows_and_skips_recorded_days(monkeypatch):
    monkeypatch.setattr(e, "read_metro_temps", lambda b: [283.15] * len(e.METROS))     # 10 C everywhere (GRIB 2t is Kelvin) -> a fixed HDD; no GRIB library needed
    lm = {"last-modified": "Tue, 17 Nov 2026 07:34:00 GMT"}
    c = FakeClient({"20261117": [R(404)], "20261116": [R(200, IDX, b"GRIBDATA", lm)]})
    conn = _db()
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    r1 = e.collect(conn, now=now, days=range(1, 4), client=c, sleep=lambda s: None)
    assert [x["new"] for x in r1] == [1, 1, 1] and all(x["init"] == "20261116" for x in r1)
    row = conn.execute("SELECT target_timestamp, available_timestamp, retrieved_timestamp, extraction_version, quality_status FROM pit_market_data WHERE agent_id='Agent_ECMWF_00z_HDD_Day1'").fetchone()
    assert row[0] == "2026-11-16T00:00:00Z" and row[1] == "2026-11-17T07:34:00Z" and row[3] == "ecmwf_hdd/2" and row[4] == "validated_approximation"
    n_calls = len(c.calls)
    r2 = e.collect(conn, now=now, days=range(1, 4), client=c, sleep=lambda s: None)
    assert [x.get("skipped") for x in r2] == ["already recorded for this run"] * 3
    assert not [u for u in c.calls[n_calls:] if u.endswith('.grib2')]                    # run discovery only: nothing is downloaded twice


def test_a_day_not_yet_published_is_reported_without_failing_the_other_days(monkeypatch):
    monkeypatch.setattr(e, "read_metro_temps", lambda b: [283.15] * len(e.METROS))
    # Day 2 needs step 36..60; make steps >= 36 unpublished while step 12..30 exist
    class C(FakeClient):
        def get(self, url, headers=None):
            import re
            m = re.search(r"-(\d+)h-oper-fc", url)
            if m and int(m.group(1)) >= 36:
                return R(404)
            return R(200, IDX, b"GRIB", {"last-modified": "Tue, 17 Nov 2026 07:34:00 GMT"})
    r = e.collect(_db(), now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc), days=range(1, 3), client=C({}), sleep=lambda s: None)
    assert r[0]["new"] == 1 and "error" in r[1] and "step" in r[1]["error"]
