CREATE TABLE IF NOT EXISTS meals_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    meal_type TEXT NOT NULL CHECK(meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    description TEXT NOT NULL,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, meal_type)
);

CREATE TABLE IF NOT EXISTS meals_grocery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL,
    quantity TEXT,
    category TEXT DEFAULT 'other',
    checked BOOLEAN DEFAULT 0,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
