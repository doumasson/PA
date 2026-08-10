-- Core key-value state (cost tracking, preferences, etc.)
CREATE TABLE IF NOT EXISTS core_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Conversation memory for context across messages
CREATE TABLE IF NOT EXISTS core_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- User preferences learned from interactions
CREATE TABLE IF NOT EXISTS core_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preference TEXT NOT NULL,
    learned_from TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Self-healing: error tracking
CREATE TABLE IF NOT EXISTS core_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin TEXT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    steps TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    last_success TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS query_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    sql_template TEXT NOT NULL,
    format_template TEXT NOT NULL,
    plugin TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Intent routing examples (learned from use)
CREATE TABLE IF NOT EXISTS core_intent_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'confirmed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_intent_examples_intent
    ON core_intent_examples(intent_id);

-- Learned action plans (message pattern → action sequence, skips Claude call)
CREATE TABLE IF NOT EXISTS core_learned_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_words TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 1,
    last_used TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
