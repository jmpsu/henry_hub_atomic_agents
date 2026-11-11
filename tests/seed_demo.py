"""Synthetic rows for smoke tests ONLY (never the production DB)."""
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
rows = [("Agent_HH_M1","2026-01-10","2026-01-10T21:00:00Z",3.41),
        ("Agent_Storage_East","2026-01-02","2026-01-08T15:30:00Z",410.0),
        ("Agent_Storage_East","2026-01-09","2026-01-15T15:30:00Z",330.0),  # future vs cutoff
        ("Agent_Weather_Actual_HDD","2026-01-10","2026-01-11T09:00:00Z",38.2),
        ("Agent_LNG_SabinePass_Flow","2026-01-10","2026-01-10T18:00:00Z",4.1e6)]
c.executemany("INSERT OR REPLACE INTO pit_market_data VALUES (?,?,?,?)", rows); c.commit()
