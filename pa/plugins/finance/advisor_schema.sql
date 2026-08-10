
CREATE TABLE IF NOT EXISTS finance_profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    balance REAL NOT NULL,
    minimum_payment REAL,
    apr REAL,
    due_date TEXT,
    status TEXT DEFAULT 'current',
    notes TEXT,
    source TEXT DEFAULT 'manual',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(institution, account_name)
);

CREATE TABLE IF NOT EXISTS finance_advisor_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT DEFAULT CURRENT_TIMESTAMP,
    summary TEXT,
    recommendations TEXT,
    questions_asked TEXT,
    data_sources TEXT
);

CREATE TABLE IF NOT EXISTS finance_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'utility',
    amount REAL,
    due_date TEXT,
    frequency TEXT DEFAULT 'monthly',
    auto_pay BOOLEAN DEFAULT 0,
    paid_this_cycle BOOLEAN DEFAULT 0,
    last_paid TEXT,
    source TEXT DEFAULT 'manual',
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS finance_budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL UNIQUE,
    monthly_limit REAL NOT NULL,
    alert_at_pct REAL NOT NULL DEFAULT 0.8,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_budget_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    month TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, month, alert_type)
);
