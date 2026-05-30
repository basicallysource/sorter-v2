CREATE TABLE IF NOT EXISTS catalog_sync_state (
    sync_type TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'idle',
    progress_current INTEGER,
    progress_total INTEGER,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    last_message TEXT,
    error TEXT,
    started_at TEXT,
    updated_at TEXT,
    completed_at TEXT
)
