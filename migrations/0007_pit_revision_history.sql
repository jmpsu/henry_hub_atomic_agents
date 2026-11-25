CREATE TABLE IF NOT EXISTS pit_revision_history (
    recorded_revision INTEGER PRIMARY KEY,
    recorded_at TEXT NOT NULL,
    op TEXT NOT NULL DEFAULT 'insert',
    agent_id TEXT NOT NULL,
    target_timestamp TEXT NOT NULL,
    available_timestamp TEXT NOT NULL,
    value REAL NOT NULL,
    source_id TEXT,
    source_url TEXT,
    retrieved_timestamp TEXT,
    published_timestamp TEXT,
    revision_timestamp TEXT,
    unit TEXT,
    geographic_scope TEXT,
    series_id TEXT,
    raw_payload_hash TEXT,
    extraction_version TEXT,
    quality_status TEXT,
    provenance TEXT
);

CREATE INDEX IF NOT EXISTS idx_pit_revision_lookup
    ON pit_revision_history (agent_id, target_timestamp, available_timestamp, recorded_revision);
CREATE INDEX IF NOT EXISTS idx_pit_revision_available
    ON pit_revision_history (available_timestamp, recorded_revision);
CREATE INDEX IF NOT EXISTS idx_pit_revision_hash
    ON pit_revision_history (raw_payload_hash);

INSERT OR IGNORE INTO pit_revision_history (
    recorded_revision, recorded_at, op, agent_id, target_timestamp, available_timestamp, value,
    source_id, source_url, retrieved_timestamp, published_timestamp, revision_timestamp, unit,
    geographic_scope, series_id, raw_payload_hash, extraction_version, quality_status, provenance)
SELECT rowid, COALESCE(retrieved_timestamp, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), 'insert',
       agent_id, target_timestamp, available_timestamp, value, source_id, source_url,
       retrieved_timestamp, published_timestamp, revision_timestamp, unit, geographic_scope,
       series_id, raw_payload_hash, extraction_version, quality_status, provenance
FROM pit_market_data;

DROP TRIGGER IF EXISTS trg_pit_market_data_revision_history;
CREATE TRIGGER trg_pit_market_data_revision_history
AFTER INSERT ON pit_market_data
BEGIN
    INSERT OR IGNORE INTO pit_revision_history (
        recorded_revision, recorded_at, op, agent_id, target_timestamp, available_timestamp, value,
        source_id, source_url, retrieved_timestamp, published_timestamp, revision_timestamp, unit,
        geographic_scope, series_id, raw_payload_hash, extraction_version, quality_status, provenance)
    VALUES (
        NEW.rowid, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'insert', NEW.agent_id, NEW.target_timestamp,
        NEW.available_timestamp, NEW.value, NEW.source_id, NEW.source_url, NEW.retrieved_timestamp,
        NEW.published_timestamp, NEW.revision_timestamp, NEW.unit, NEW.geographic_scope, NEW.series_id,
        NEW.raw_payload_hash, NEW.extraction_version, NEW.quality_status, NEW.provenance);
END;
