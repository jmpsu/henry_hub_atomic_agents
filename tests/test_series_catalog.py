import sqlite3
import init_db
import ingest
import backtest
import series_catalog as sc


def test_trigger_sync_and_unit_guard(tmp_path):
    db = str(tmp_path / "test.db")
    init_db.migrate(db)
    conn = sqlite3.connect(db)

    assert ingest.record_observation(
        conn,
        agent_id="Agent_HH_Spot_EIA",
        target_timestamp="2026-11-18T00:00:00Z",
        available_timestamp="2026-11-18T15:00:00Z",
        value=2.85,
        source_id="eia_dnav_ng",
        unit="USD/MMBtu",
        geographic_scope="Henry Hub, LA",
        series_id="RNGWHHD",
    )
    conn.commit()

    rows = sc.list_series(conn, domain="henry_hub_pricing")
    assert len(rows) == 1
    assert rows[0]["observation_count"] == 1
    assert rows[0]["frequency"] == "daily"

    # Unit mismatch against active cataloged unit should be rejected
    try:
        ingest.record_observation(
            conn,
            agent_id="Agent_HH_Spot_EIA",
            target_timestamp="2026-11-19T00:00:00Z",
            available_timestamp="2026-11-19T15:00:00Z",
            value=2.90,
            source_id="eia_dnav_ng",
            unit="EUR/MWh",
            series_id="RNGWHHD",
        )
        assert False, "Expected unit mismatch error"
    except ValueError as exc:
        assert "conflicts with cataloged" in str(exc)

    dom = backtest.catalog_domain_series(conn, "henry_hub_pricing", "2026-11-20T00:00:00Z", "2026-11-01T00:00:00Z")
    assert dom == {"Agent_HH_Spot_EIA": {"2026-11-18": 2.85}}


def test_feed_status_classifies_planned_unregistered_active_and_stale(tmp_path):
    db = str(tmp_path / "feed.db")
    init_db.migrate(db)
    conn = sqlite3.connect(db)
    planned = sc.feed_status(conn, "Agent_LNG_JKM_Forward", "2026-11-20T00:00:00Z")
    assert planned["status"] == "INACTIVE_OR_PLANNED_GAP" and planned["label"] == "Feed Not Configured"
    assert planned["source_ids"] == ["planned_gap"]
    assert sc.feed_status(conn, "Agent_Not_In_Catalog", "2026-11-20T00:00:00Z")["status"] == "UNREGISTERED"
    assert "Agent_LNG_JKM_Forward" not in sc.active_agents(conn)
    ingest.record_observation(conn, agent_id="Agent_HH_Spot_EIA", target_timestamp="2026-11-18T00:00:00Z",
                              available_timestamp="2026-11-18T15:00:00Z", value=2.85, source_id="eia_dnav_ng",
                              unit="USD/MMBtu", series_id="RNGWHHD")
    conn.commit()
    fresh = sc.feed_status(conn, "Agent_HH_Spot_EIA", "2026-11-20T00:00:00Z")
    assert fresh["status"] == "ACTIVE" and fresh["cadence_days"] == 1.0
    stale = sc.feed_status(conn, "Agent_HH_Spot_EIA", "2026-12-05T00:00:00Z")
    assert stale["status"] == "STALE" and stale["age_days"] > 1
