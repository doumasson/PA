CREATE TABLE IF NOT EXISTS repair_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT '',
    -- queued -> diagnosing -> awaiting_approval -> approved -> applying
    --   -> applied | failed | rejected | closed
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT,
    diff TEXT,
    branch TEXT,
    -- 0 = nothing sent, 1 = approval request sent, 2 = final outcome sent
    notified INTEGER NOT NULL DEFAULT 0,
    detail TEXT,
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS repair_queue_status ON repair_queue(status);
