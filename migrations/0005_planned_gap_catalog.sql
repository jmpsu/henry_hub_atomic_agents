INSERT OR IGNORE INTO series_catalog (agent_id, series_id, source_id, domain, frequency, unit, is_active)
VALUES
    ('Agent_LNG_JKM_Forward', 'Agent_LNG_JKM_Forward', 'planned_gap', 'global_gas_pricing', 'daily', 'USD/MMBtu', 0),
    ('Agent_NATGAS_AECO_Basis', 'Agent_NATGAS_AECO_Basis', 'planned_gap', 'henry_hub_pricing', 'daily', 'USD/MMBtu', 0),
    ('Agent_NATGAS_Waha_Basis', 'Agent_NATGAS_Waha_Basis', 'planned_gap', 'henry_hub_pricing', 'daily', 'USD/MMBtu', 0),
    ('Agent_Gas_Waha_Spot', 'Agent_Gas_Waha_Spot', 'planned_gap', 'henry_hub_pricing', 'daily', 'USD/MMBtu', 0),
    ('Agent_Houston_ShipChannel_Basis', 'Agent_Houston_ShipChannel_Basis', 'planned_gap', 'henry_hub_pricing', 'daily', 'USD/MMBtu', 0),
    ('Agent_NATGAS_TranscoZone6_Basis', 'Agent_NATGAS_TranscoZone6_Basis', 'planned_gap', 'henry_hub_pricing', 'daily', 'USD/MMBtu', 0),
    ('Agent_NGL_Conway_Propane', 'Agent_NGL_Conway_Propane', 'planned_gap', 'ngl_markets', 'daily', 'cents/gal', 0),
    ('Agent_NGL_MontBelvieu_Ethane', 'Agent_NGL_MontBelvieu_Ethane', 'planned_gap', 'ngl_markets', 'daily', 'cents/gal', 0),
    ('Agent_NGL_MontBelvieu_NormalButane', 'Agent_NGL_MontBelvieu_NormalButane', 'planned_gap', 'ngl_markets', 'daily', 'cents/gal', 0),
    ('Agent_NGL_MontBelvieu_Isobutane', 'Agent_NGL_MontBelvieu_Isobutane', 'planned_gap', 'ngl_markets', 'daily', 'cents/gal', 0),
    ('Agent_NGL_MontBelvieu_NatGasoline', 'Agent_NGL_MontBelvieu_NatGasoline', 'planned_gap', 'ngl_markets', 'daily', 'cents/gal', 0);

UPDATE series_catalog
SET is_active = 0
WHERE unit IS NULL OR TRIM(unit) = '' OR UPPER(TRIM(unit)) = 'NONE';
