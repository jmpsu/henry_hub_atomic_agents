"""Synthetic rows for smoke tests ONLY (never the production DB). Insert-only, labelled synthetic."""
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
rows = [("Agent_HH_M1","2026-01-10T00:00:00Z","2026-01-10T21:00:00Z",3.41),
        ("Agent_Storage_East","2026-01-02T00:00:00Z","2026-01-08T15:30:00Z",410.0),
        ("Agent_Storage_East","2026-01-09T00:00:00Z","2026-01-15T15:30:00Z",330.0),  # future vs cutoff
        ("Agent_Weather_Actual_HDD","2026-01-10T00:00:00Z","2026-01-11T09:00:00Z",38.2),
        ("Agent_LNG_SabinePass_Flow","2026-01-10T00:00:00Z","2026-01-10T18:00:00Z",4.1e6)]
c.executemany("INSERT OR IGNORE INTO pit_market_data (agent_id,target_timestamp,available_timestamp,value,source_id,quality_status,provenance) "
              "VALUES (?,?,?,?,'seed_demo','unverified_seed','synthetic_scenario')", rows); c.commit()
