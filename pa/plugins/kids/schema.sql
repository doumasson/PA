CREATE TABLE IF NOT EXISTS kids_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    kid TEXT NOT NULL CHECK(kid IN ('maddox', 'asher')),
    note TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
