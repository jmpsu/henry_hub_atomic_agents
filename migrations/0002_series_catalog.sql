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

INSERT INTO series_catalog (
    agent_id,
    series_id,
    source_id,
    domain,
    frequency,
    unit,
    geographic_scope,
    first_target_timestamp,
    last_target_timestamp,
    observation_count,
    is_active
)
SELECT
    agent_id,
    COALESCE(NULLIF(TRIM(series_id), ''), agent_id) AS norm_series_id,
    COALESCE(NULLIF(TRIM(source_id), ''), 'unassigned') AS norm_source_id,
    CASE
        WHEN agent_id LIKE 'Agent_Ambient%' THEN 'weather_metar'
        WHEN agent_id LIKE 'Agent_ECMWF_%' OR agent_id LIKE 'Agent_GFS_%' THEN 'weather_forecast'
        WHEN agent_id LIKE 'Agent_Weather_%' THEN 'weather_degree_days'
        WHEN agent_id LIKE 'Agent_HH_%' THEN 'henry_hub_pricing'
        WHEN agent_id LIKE 'Agent_TTF_%' THEN 'global_gas_pricing'
        WHEN agent_id LIKE 'Agent_Storage_%' THEN 'ng_storage'
        WHEN agent_id LIKE 'Agent_Prod_%' THEN 'ng_production'
        WHEN agent_id LIKE 'Agent_Demand_%' THEN 'ng_demand'
        WHEN agent_id LIKE 'Agent_BorderFlow_%' THEN 'ng_border_flows'
        WHEN agent_id LIKE 'Agent_LNG%' THEN 'lng_exports_feedgas'
        WHEN agent_id LIKE 'Agent_Coal_%' THEN 'coal_markets'
        WHEN agent_id LIKE 'Agent_Crude_%' THEN 'crude_oil'
        WHEN agent_id LIKE 'Agent_NGL_%' THEN 'ngl_markets'
        WHEN agent_id LIKE 'Agent_Power_%' THEN 'power_emissions'
        WHEN agent_id LIKE 'Agent_FX_%' THEN 'fx_rates'
        ELSE 'other'
    END AS domain,
    CASE
        WHEN source_id = 'noaa_awc_metar' THEN 'hourly'
        WHEN source_id IN ('ecmwf_open_data', 'noaa_gfs_open_data') THEN 'daily_forecast'
        WHEN source_id = 'eia_wngsr' THEN 'weekly'
        WHEN source_id IN ('eia_ng_bulk', 'eia_steo_bulk') THEN 'monthly'
        WHEN source_id = 'eia_coal_markets' THEN 'weekly'
        WHEN source_id = 'eia_coal_transportation' THEN 'annual'
        WHEN source_id = 'rggi_auction_results' THEN 'quarterly_auction'
        WHEN source_id IN (
            'eia_dnav_ng', 'eia_dnav_pet', 'yahoo_finance_nymex',
            'eia930_balance', 'lng_feedgas_model',
            'noaa_cpc_degree_days', 'noaa_cpc_degree_days_history',
            'derived_from_noaa_cpc_degree_days_history'
        ) THEN 'daily'
        ELSE 'irregular'
    END AS frequency,
    MAX(NULLIF(TRIM(unit), '')) AS unit,
    MAX(NULLIF(TRIM(geographic_scope), '')) AS geographic_scope,
    MIN(target_timestamp) AS first_target_timestamp,
    MAX(target_timestamp) AS last_target_timestamp,
    COUNT(*) AS observation_count,
    CASE
        WHEN source_id = 'eia_dnav_ng' AND agent_id LIKE 'Agent_HH_M%' THEN 0
        WHEN NULLIF(TRIM(source_id), '') IS NULL THEN 0
        ELSE 1
    END AS is_active
FROM pit_market_data
GROUP BY
    agent_id,
    norm_series_id,
    norm_source_id
ON CONFLICT(agent_id, series_id, source_id) DO UPDATE SET
    domain = excluded.domain,
    frequency = excluded.frequency,
    unit = COALESCE(excluded.unit, series_catalog.unit),
    geographic_scope = COALESCE(excluded.geographic_scope, series_catalog.geographic_scope),
    first_target_timestamp = excluded.first_target_timestamp,
    last_target_timestamp = excluded.last_target_timestamp,
    observation_count = excluded.observation_count,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
