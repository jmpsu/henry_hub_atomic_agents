CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    cutoff TEXT NOT NULL,
    prompt TEXT NOT NULL,
    intent TEXT,
    entities TEXT,
    node_ids TEXT,
    chunk_ids TEXT,
    fact_ids TEXT,
    model TEXT,
    verdict TEXT,
    answer TEXT,
    first_event_ms INTEGER,
    total_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_chat_log_ts ON chat_log(ts);
