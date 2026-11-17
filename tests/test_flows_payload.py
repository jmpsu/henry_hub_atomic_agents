"""EIA monthly LNG exports and border volumes reach the API, the driver panels and the map, without touching the daily-meter count."""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _scratch  # noqa: E402
import init_db  # noqa: E402
import markets_engine as me  # noqa: E402
from collectors import eia_ng_flows as f  # noqa: E402
from test_eia_ng_flows import _fetcher, _zip  # noqa: E402


def _state():
    db = str(Path(_scratch.mkdtemp()) / "t.db")
    init_db.migrate(db)
    conn = sqlite3.connect(db)
    f.collect(conn, fetcher=_fetcher(_zip()), now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
    conn.close()
    return me.build_state(db, as_of="2026-12-31T00:00:00Z")


def test_new_driver_groups_carry_measured_monthly_values_with_units():
    st = _state()
    g = {x["group"]: x for x in st["drivers"]}
    assert [i["agent_id"] for i in g["lng_exports"]["items"]][0] == "Agent_LNGExports_SabinePass" and len(g["lng_exports"]["items"]) == 8
    assert len(g["border_flows"]["items"]) == 5
    for grp in ("lng_exports", "border_flows"):
        for it in g[grp]["items"]:
            assert it["value"] is not None and it["unit"] == "MMcf/month" and it["provenance"] == "measured"
    assert g["lng"]["items"][0]["value"] is None                                     # the daily feedgas meters remain honestly pending


def test_map_nodes_for_lng_terminals_show_the_monthly_exports():
    st = _state()
    nodes = {n["id"]: n for n in st["geo"]["nodes"]}
    for nid in ("SAB", "CRP", "FPT", "CAM", "CCP", "PLQ", "ELB", "CVP"):
        assert nodes[nid]["status"] == "measured" and nodes[nid]["unit"] == "MMcf/month" and nodes[nid]["date"] == "2026-08-01"


def test_daily_meter_count_is_unchanged_and_the_alert_says_monthly_volumes_are_separate():
    st = _state()
    assert st["geo"]["flow_agents_total"] == 13 and st["geo"]["flow_agents_collected"] == 0
    assert any("Daily pipeline and LNG meters: 0 of 13" in a["text"] and "monthly" in a["text"] for a in st["alerts"])


def test_roster_describes_the_new_agents_and_marks_inferred_mappings():
    st = _state()
    by = {s["agent_id"]: s for s in st["sources"]}
    assert by["Agent_LNGExports_SabinePass"]["status"] == "collected" and "MONTH" in by["Agent_LNGExports_SabinePass"]["series"]
    assert "INFERRED" in by["Agent_BorderFlow_RioGrande_ToMexico"]["intended_source"] and "INFERRED" in by["Agent_BorderFlow_Brownsville_ToMexico"]["intended_source"]
    assert "INFERRED" not in by["Agent_BorderFlow_Eastport_FromCanada"]["intended_source"]
    assert st["platform"]["roster_agents"] == 94
    assert not [s for s in st["sources"] if s["agent_id"].startswith(("Agent_LNGExports_", "Agent_BorderFlow_")) and s["status"] == "collected" and not s["contributes"]]


def test_no_stale_alert_for_a_monthly_series_published_two_months_ago():
    st = _state()
    assert not any(a["kind"] == "freshness" and ("LNGExports" in a["text"] or "BorderFlow" in a["text"]) for a in st["alerts"])
