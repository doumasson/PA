CREATE TABLE IF NOT EXISTS kids_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- TODO: CHECK constraint hardcodes kid names. SQLite cannot alter CHECK
    -- constraints in place (migrating requires a table rebuild + data copy).
    -- Left as-is for now — Python code derives kid names from the profile.
    kid TEXT NOT NULL CHECK(kid IN ('maddox', 'asher')),
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    date TEXT,
    time TEXT,
    location TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kids_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- TODO: same hardcoded CHECK as kids_events (see note above).
    kid TEXT NOT NULL CHECK(kid IN ('maddox', 'asher')),
    note TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
