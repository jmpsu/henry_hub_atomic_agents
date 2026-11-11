import sqlite3, sys
path = sys.argv[1] if len(sys.argv) > 1 else "henry_hub_pit.db"
c = sqlite3.connect(path)
c.executescript("""
CREATE TABLE IF NOT EXISTS pit_market_data (
  agent_id TEXT NOT NULL, target_timestamp TEXT NOT NULL,
  available_timestamp TEXT NOT NULL, value REAL NOT NULL,
  PRIMARY KEY (agent_id, target_timestamp, available_timestamp));
CREATE INDEX IF NOT EXISTS idx_pit_backtest ON pit_market_data (available_timestamp, agent_id);""")
c.commit(); print("initialized", path)
