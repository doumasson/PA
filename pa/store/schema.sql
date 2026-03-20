CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('checking', 'savings', 'credit_card', 'mortgage', 'loan')),
    interest_rate REAL,
    credit_limit REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    balance REAL NOT NULL,
    statement_balance REAL,
    available_credit REAL,
    minimum_payment REAL,
    due_date DATE,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    date DATE NOT NULL,
    posted_date DATE,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT,
    dedup_hash TEXT UNIQUE NOT NULL,
    is_pending BOOLEAN DEFAULT 0,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    status TEXT NOT NULL CHECK(status IN ('success', 'failure', 'mfa_pending')),
    error_message TEXT,
    duration_seconds REAL,
    ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
