# Collectors: what is real and what is NOT

Implemented against live, verified sources (fixture-tested):
- `cpc_degree_days.py`: NOAA CPC CONUS population-weighted HDD/CDD (keyless).
- `eia_storage.py`: EIA weekly storage report CSV, six regions (keyless; real release timestamp).

NOT implemented (do not assume these exist when debugging missing data):
- NGI cash prices, CME futures, pipeline EBBs (Cheniere, TC Energy, ...): licensed/credentialed or structurally
  unverified. Earlier pasted templates for them used invented selectors/URLs/facet codes. Writing them without access
  would create collectors that fail or silently return wrong numbers. Verify the real endpoint and structure first.
- EIA API v2 agents (production, power burn, ...): need an EIA API key (EIA_API_KEY) and verified route/facet codes.
GFS/ECMWF forecast collectors are implemented; they need the ECCODES system library (`libeccodes-dev` on Debian/Ubuntu) and the
`pygrib` Python binding from `requirements.txt`. Install with `apt-get install -y libeccodes-dev` before `pip install -r requirements.txt`.
If a run fails or a series is empty, check here first: the collector may simply not exist or its source layout changed.

## Status (2026-11-12): 36 of the 81 roster agents collect real data
- cpc_degree_days: Agent_Weather_Actual_HDD/CDD (2)
- eia_storage: six storage regions (6)
- eia_prices: Agent_HH_M1..M4 (HISTORICAL ONLY, EIA series ended 2024-04-05) (4) + Agent_HH_Spot_EIA (extra, not in roster; EIA/Refinitiv spot, not NGI)
- gfs_hdd: Agent_GFS_00z_HDD_Day1..15 (15)  -- approximation, corr ~0.59 / bias ~-4 HDD vs CPC observed; calibrate before using levels
- ecmwf_hdd: Agent_ECMWF_00z_HDD_Day1..9 (9) -- Days 10-15 NOT available in the open-data HRES feed
Still missing: NGI cash x4, CME futures M5..M12 (8), pipeline/EBB flows (~20), EIA production x6, power burn/industrial/res-comm,
weather 30yr normal, coal x3, RGGI CO2, ECMWF Day10-15 (6), Agent_HH_M1..M4 live feed.
Rows with provenance 'unverified_seed' predate the collectors and have unknown origin; they are excluded from measured snapshots.

## History backfill (cpc_history.py, one-off)
Loads CPC CONUS observed HDD/CDD 1981–(current year-1) (available D+1 12:00Z, assumed) and derives
`Agent_Weather_30YrNormal_HDD` (1991–2020 mean per calendar day, provenance `extracted_estimate`, available 2021-05-04).
Run: `DB_PATH=… .venv/bin/python collectors/cpc_history.py` (idempotent; INSERT OR IGNORE).
