"""Create/migrate the PIT schema. Additive and idempotent: never drops or rewrites rows.
Usage: python init_db.py [path]   (defaults to $DB_PATH or ./henry_hub_pit.db)"""
import os
import sqlite3
import sys

PRODUCTION_COLUMNS = {
    "source_id": "TEXT",
    "source_url": "TEXT",
    "retrieved_timestamp": "TEXT",
    "published_timestamp": "TEXT",
    "revision_timestamp": "TEXT",
    "unit": "TEXT",
    "geographic_scope": "TEXT",
    "series_id": "TEXT",
    "raw_payload_hash": "TEXT",
    "extraction_version": "TEXT",
    "quality_status": "TEXT DEFAULT 'unvalidated'",
    "provenance": "TEXT",
}


def migrate(path: str) -> list:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pit_market_data (
            agent_id TEXT NOT NULL, target_timestamp TEXT NOT NULL,
            available_timestamp TEXT NOT NULL, value REAL NOT NULL,
            PRIMARY KEY (agent_id, target_timestamp, available_timestamp));
        CREATE INDEX IF NOT EXISTS idx_pit_backtest
            ON pit_market_data (available_timestamp, agent_id);
        CREATE TABLE IF NOT EXISTS raw_payloads (
            raw_payload_hash TEXT PRIMARY KEY, source_id TEXT, source_url TEXT,
            http_status INTEGER, retrieved_timestamp TEXT NOT NULL,
            content_type TEXT, byte_length INTEGER, archive_path TEXT NOT NULL);
        """
    )
    have = {r[1] for r in conn.execute("PRAGMA table_info(pit_market_data)")}
    added = []
    for col, decl in PRODUCTION_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE pit_market_data ADD COLUMN {col} {decl}")
            added.append(col)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pit_agent_target ON pit_market_data (agent_id, target_timestamp, available_timestamp)")

    conn.executescript("""
-- 0002_series_catalog.sql
-- Creates and populates series_catalog from live production series in pit_market_data

CREATE TABLE IF NOT EXISTS series_catalog (
    catalog_id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    series_id TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL,
    frequency TEXT NOT NULL,
    unit TEXT,
    geographic_scope TEXT,
    first_target_timestamp TEXT,
    last_target_timestamp TEXT,
    observation_count INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(agent_id, series_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_series_catalog_agent ON series_catalog(agent_id);
CREATE INDEX IF NOT EXISTS idx_series_catalog_domain ON series_catalog(domain);
CREATE INDEX IF NOT EXISTS idx_series_catalog_source ON series_catalog(source_id);
-- 0003_series_catalog_sync.sql
-- Automatically keeps series_catalog metadata up to date on every pit_market_data insert

DROP TRIGGER IF EXISTS trg_pit_market_data_sync_catalog;

CREATE TRIGGER trg_pit_market_data_sync_catalog
AFTER INSERT ON pit_market_data
BEGIN
    INSERT INTO series_catalog (
        agent_id, series_id, source_id, domain, frequency,
        unit, geographic_scope, first_target_timestamp, last_target_timestamp,
        observation_count, is_active
    )
    VALUES (
        NEW.agent_id,
        COALESCE(NULLIF(TRIM(NEW.series_id), ''), NEW.agent_id),
        COALESCE(NULLIF(TRIM(NEW.source_id), ''), 'unassigned'),
        CASE
            WHEN NEW.agent_id LIKE 'Agent_Ambient%' THEN 'weather_metar'
            WHEN NEW.agent_id LIKE 'Agent_ECMWF_%' OR NEW.agent_id LIKE 'Agent_GFS_%' THEN 'weather_forecast'
            WHEN NEW.agent_id LIKE 'Agent_Weather_%' THEN 'weather_degree_days'
            WHEN NEW.agent_id LIKE 'Agent_HH_%' THEN 'henry_hub_pricing'
            WHEN NEW.agent_id LIKE 'Agent_TTF_%' THEN 'global_gas_pricing'
            WHEN NEW.agent_id LIKE 'Agent_Storage_%' THEN 'ng_storage'
            WHEN NEW.agent_id LIKE 'Agent_Prod_%' THEN 'ng_production'
            WHEN NEW.agent_id LIKE 'Agent_Demand_%' THEN 'ng_demand'
            WHEN NEW.agent_id LIKE 'Agent_BorderFlow_%' THEN 'ng_border_flows'
            WHEN NEW.agent_id LIKE 'Agent_LNG%' THEN 'lng_exports_feedgas'
            WHEN NEW.agent_id LIKE 'Agent_Coal_%' THEN 'coal_markets'
            WHEN NEW.agent_id LIKE 'Agent_Crude_%' THEN 'crude_oil'
            WHEN NEW.agent_id LIKE 'Agent_NGL_%' THEN 'ngl_markets'
            WHEN NEW.agent_id LIKE 'Agent_Power_%' THEN 'power_emissions'
            WHEN NEW.agent_id LIKE 'Agent_FX_%' THEN 'fx_rates'
            ELSE 'other'
        END,
        CASE
            WHEN NEW.source_id = 'noaa_awc_metar' THEN 'hourly'
            WHEN NEW.source_id IN ('ecmwf_open_data', 'noaa_gfs_open_data') THEN 'daily_forecast'
            WHEN NEW.source_id IN ('eia_wngsr', 'eia_coal_markets') THEN 'weekly'
            WHEN NEW.source_id IN ('eia_ng_bulk', 'eia_steo_bulk') THEN 'monthly'
            WHEN NEW.source_id = 'eia_coal_transportation' THEN 'annual'
            WHEN NEW.source_id = 'rggi_auction_results' THEN 'quarterly_auction'
            WHEN NEW.source_id IN (
                'eia_dnav_ng', 'eia_dnav_pet', 'yahoo_finance_nymex',
                'eia930_balance', 'lng_feedgas_model',
                'noaa_cpc_degree_days', 'noaa_cpc_degree_days_history',
                'derived_from_noaa_cpc_degree_days_history'
            ) THEN 'daily'
            ELSE 'irregular'
        END,
        NULLIF(TRIM(NEW.unit), ''),
        NULLIF(TRIM(NEW.geographic_scope), ''),
        NEW.target_timestamp,
        NEW.target_timestamp,
        1,
        CASE
            WHEN NEW.source_id = 'eia_dnav_ng' AND NEW.agent_id LIKE 'Agent_HH_M%' THEN 0
            WHEN NULLIF(TRIM(NEW.source_id), '') IS NULL THEN 0
            WHEN COALESCE(NEW.quality_status, '') = 'unverified_seed' THEN 0
            ELSE 1
        END
    )
    ON CONFLICT(agent_id, series_id, source_id) DO UPDATE SET
        unit = COALESCE(excluded.unit, series_catalog.unit),
        geographic_scope = COALESCE(excluded.geographic_scope, series_catalog.geographic_scope),
        first_target_timestamp = MIN(series_catalog.first_target_timestamp, excluded.first_target_timestamp),
        last_target_timestamp = MAX(series_catalog.last_target_timestamp, excluded.last_target_timestamp),
        observation_count = series_catalog.observation_count + 1,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
END;
    """)
    conn.commit()
    conn.close()
    return added


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DB_PATH", "henry_hub_pit.db")
    print("migrated", target, "added columns:", migrate(target))
