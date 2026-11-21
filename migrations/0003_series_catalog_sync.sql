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
