CREATE TABLE IF NOT EXISTS agent_iterations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    build_status TEXT,
    screenshot_desc TEXT,
    what_happened TEXT,
    files_changed TEXT,
    succeeded INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_signature TEXT UNIQUE NOT NULL,
    fix_that_worked TEXT NOT NULL,
    file_affected TEXT,
    times_applied INTEGER DEFAULT 1,
    last_used TEXT
);

CREATE TABLE IF NOT EXISTS agent_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson TEXT NOT NULL,
    learned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'agent'
);

CREATE TABLE IF NOT EXISTS agent_game_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_screen_status (
    screen_name TEXT PRIMARY KEY,
    file_path TEXT,
    last_confirmed_working TEXT,
    last_broke TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS agent_self_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    test_code TEXT NOT NULL,
    last_run TEXT,
    last_result TEXT,
    times_run INTEGER DEFAULT 0
);
