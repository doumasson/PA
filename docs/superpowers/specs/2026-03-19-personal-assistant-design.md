# Personal Assistant (PA) — Design Spec

## Overview

A personal financial assistant that automatically collects financial data from bank and credit card websites via browser automation, stores it in an encrypted local database, and provides insights, alerts, and debt management advice through a Telegram bot interface — powered by Claude API for intelligent analysis.

**Design philosophy:** Safe, read-only, locally encrypted, extensible. Inspired by OpenClaw's agentic approach but with strict guardrails — the PA observes and advises, it never moves money.

## Architecture

Modular monolith — single Python process with clean internal boundaries.

```
pa/
  __main__.py        # Entry point, wires modules together
  config/            # Settings management and user preferences
  vault/             # Credential encryption/decryption
  scrapers/          # One scraper per financial institution
  store/             # SQLite data layer
  bot/               # Telegram bot interface
  scheduler/         # APScheduler job runner
  brain/             # Claude API integration for analysis
```

### Concurrency Model

The application is **asyncio-based throughout:**
- `python-telegram-bot` v20+ is natively asyncio
- Playwright async API (`async_playwright`)
- APScheduler 4.x with asyncio scheduler (`AsyncScheduler`)
- All module interfaces are async (`async def`)

**Single event loop** runs in the main thread. All I/O (Playwright, Telegram, Claude API, SQLite) is non-blocking. This avoids thread-safety issues and simplifies the MFA callback flow (see Scrapers section).

**SQLite access** uses `aiosqlite` for async queries. SQLCipher is loaded as an extension.

### System Diagram

```
┌─────────────────────────────────────────────────┐
│                    PA System                     │
│                                                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ Telegram  │  │ Scheduler │  │    Brain     │  │
│  │   Bot     │←→│(APScheduler)│←→│ (Claude API) │  │
│  └────┬─────┘  └─────┬─────┘  └──────┬───────┘  │
│       │               │               │          │
│       └───────┬───────┴───────┬───────┘          │
│               │               │                  │
│         ┌─────▼─────┐  ┌─────▼──────┐           │
│         │   Store   │  │  Scrapers  │           │
│         │ (SQLite)  │  │(Playwright)│           │
│         └───────────┘  └─────┬──────┘           │
│                              │                  │
│                        ┌─────▼──────┐           │
│                        │   Vault    │           │
│                        │(Encrypted) │           │
│                        └────────────┘           │
└─────────────────────────────────────────────────┘
```

## Module Specifications

### 1. Vault (Credential Security)

**Purpose:** Securely store and retrieve financial institution credentials.

**Encryption scheme:**
- Master password entered by user at startup
- Key derivation: Argon2id (memory-hard, GPU-resistant)
- Encryption: AES-256-GCM
- Storage: Single encrypted binary file `vault.enc`

**Decrypted structure (JSON in memory only):**
```json
{
  "wellsfargo": {
    "username": "...",
    "password": "...",
    "mfa_method": "sms",
    "security_questions": {}
  },
  "synchrony": {
    "username": "...",
    "password": "..."
  }
}
```

**Key derivation:** Argon2id derives a 256-bit key from the master password. This key is used directly for:
1. AES-256-GCM encryption of `vault.enc`
2. SQLCipher raw key (passed via `PRAGMA key` as a hex blob, bypassing SQLCipher's built-in PBKDF2)

This means one KDF, one key, two consumers. The Argon2id parameters (memory cost, time cost, parallelism) are stored unencrypted alongside `vault.enc` so they can be used to re-derive the key from the master password.

**Security rules:**
- Decrypted credentials exist in memory for the lifetime of the unlocked vault session
- On `lock()`, all credential data is overwritten and dereferenced (best-effort via ctypes memset)
- No master password stored anywhere — entered at runtime only
- After reboot, master password must be re-entered via Telegram `/unlock` command
- Both the password message and prompt are deleted from Telegram immediately after processing

**Error handling:**
- `Vault.unlock()` raises `VaultAuthError` on wrong password (detected via GCM authentication tag failure)
- `Vault.get()` raises `VaultLockedError` if called before unlock
- `Vault.add()` raises `VaultLockedError` if vault is locked

**Interface:**
- `Vault.unlock(master_password)` → decrypts vault, loads credentials into memory
- `Vault.lock()` → wipes credentials from memory
- `Vault.get(institution_name)` → returns credentials dict for a given institution
- `Vault.add(institution_name, credentials)` → adds/updates credentials, re-encrypts vault
- `Vault.is_unlocked` → boolean property

### 2. Scrapers (Browser Automation)

**Purpose:** Log into financial institution websites and extract account data.

**Technology:** Playwright (Chromium) with stealth settings.

**Structure:**
```
scrapers/
  base.py            # Abstract base class
  wellsfargo.py
  synchrony.py
  credit_one.py
  ...
```

**Base scraper interface:**
- `login(credentials)` → authenticate, handle MFA
- `get_balances()` → returns: balance, available_credit, minimum_payment, due_date
- `get_transactions(since_date)` → returns list of transactions
- `logout()` → clean session close

**MFA handling (async callback flow):**
1. Scraper detects MFA challenge (SMS code, email code, security question)
2. Scraper creates an `asyncio.Event` and registers it with the Bot module via a shared `MFABridge`
3. Bot sends Telegram message: "Wells Fargo is asking for an MFA code. Reply with the code."
4. User replies with the code → Bot sets the code on the `MFABridge` and triggers the Event
5. Scraper awaits the Event (with a 5-minute timeout), retrieves the code, and continues
6. On timeout: scraper aborts, logs failure, Bot alerts user "MFA timed out for Wells Fargo"

**MFABridge interface:**
- `request_mfa(institution, prompt) -> str` — called by scraper, blocks until user responds or timeout
- `provide_mfa(institution, code)` — called by bot when user sends the code

**Memory management:**
- One Playwright browser instance shared across all scrapers
- One browser context per institution, closed after each scrape session
- Scrapers run sequentially (never parallel) to keep memory under ~500MB total
- Explicit `await context.close()` after each institution completes

**Anti-detection:**
- Realistic browser fingerprint (Playwright stealth plugin)
- Human-like delays between page actions
- No parallel logins to the same institution
- Slightly randomized scrape times

**Target institutions (initial):**
- Wells Fargo (checking/savings)
- Synchrony Bank (credit card)
- Credit One (credit card)
- ~8 additional credit card issuers (to be added as needed)
- Mortgage servicer (TBD)

### 3. Store (SQLite Database)

**Purpose:** Persist all financial data with history for trend analysis.

**Encryption:** SQLCipher (encrypted SQLite). The raw key is the same Argon2id-derived 256-bit key used by the Vault (see Vault section). Passed to SQLCipher via `PRAGMA key = "x'...'"` (hex blob), bypassing SQLCipher's default PBKDF2. Accessed via `aiosqlite` with SQLCipher extension loaded.

**Schema:**

**accounts**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| institution | TEXT | e.g., "wellsfargo" |
| name | TEXT | e.g., "Chase Sapphire" |
| type | TEXT | checking, savings, credit_card, mortgage, loan |
| interest_rate | REAL | APR as decimal |
| credit_limit | REAL | Null for non-credit accounts |
| created_at | TIMESTAMP | |

**balances**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| account_id | INTEGER FK | References accounts.id |
| balance | REAL | Current balance/amount owed |
| statement_balance | REAL | Statement balance (what's owed to avoid interest). Null if N/A |
| available_credit | REAL | Null for non-credit accounts |
| minimum_payment | REAL | Null if N/A |
| due_date | DATE | Next payment due date |
| scraped_at | TIMESTAMP | When this snapshot was taken |

**transactions**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| account_id | INTEGER FK | References accounts.id |
| date | DATE | Transaction date |
| posted_date | DATE | Posted date (null if still pending) |
| description | TEXT | Merchant/description |
| amount | REAL | Positive = charge, negative = payment |
| category | TEXT | Auto-assigned by Brain |
| dedup_hash | TEXT UNIQUE | SHA-256 of (account_id + date + description + amount). Prevents duplicate inserts |
| is_pending | BOOLEAN | True if transaction hasn't posted yet |
| scraped_at | TIMESTAMP | |

**Deduplication:** On insert, compute `dedup_hash = sha256(f"{account_id}|{date}|{description}|{amount}")`. Use `INSERT OR IGNORE` to skip duplicates. Pending transactions are updated to posted when `posted_date` appears in a later scrape.

**scrape_log**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| institution | TEXT | Which scraper ran |
| account_id | INTEGER FK | References accounts.id (null for institution-level events) |
| status | TEXT | success, failure, mfa_pending |
| error_message | TEXT | Null on success |
| duration_seconds | REAL | How long the scrape took |
| ran_at | TIMESTAMP | |

### 4. Brain (Claude API Integration)

**Purpose:** Intelligent analysis, insights, and conversation about financial data.

**System prompt context (refreshed before each query):**
- All accounts with current balances and interest rates
- User's income (configured during setup)
- Financial goals (e.g., "debt-free in 2 years")
- User preferences (e.g., "don't recommend closing oldest card")

**Tiered model usage:**
| Tier | Model | Use case | Cost |
|------|-------|----------|------|
| Fast | Haiku | Simple lookups, balance checks, formatting | ~$0.001/query |
| Standard | Sonnet | Spending analysis, categorization, pattern detection | ~$0.01/query |
| Deep | Opus | Debt payoff strategy, comprehensive financial planning | ~$0.10/query |

**Auto-tier selection:** Local keyword/regex heuristic (no API call needed). Rules:
- Queries matching balance/due/status keywords → Haiku
- Queries involving "spending", "category", "compare", "trend" → Sonnet
- Queries involving "plan", "strategy", "budget", "payoff", "advice" → Opus
- User can override with `/ask-deep <question>` to force Opus

**Cost controls:**
- Monthly API cost cap (default $20, configurable). Alert at 80%, hard stop at 100%.
- Rate limit: max 30 queries per hour (prevents runaway loops)
- Retry with exponential backoff on API errors (max 3 retries)

**Error handling:**
- API timeout/error → return "Brain temporarily unavailable, try again shortly" via Telegram
- Rate limit hit → queue the request and notify user of delay

**Proactive insights (scheduler-triggered):**
- Payment due reminders (3 days, 1 day, day-of)
- Spending anomaly detection
- Weekly spending summary
- Monthly debt progress report
- Interest savings opportunities

### 5. Scheduler (APScheduler)

**Purpose:** Run scraping jobs and analysis tasks on configurable intervals.

**Default schedule:**
| Job | Frequency | Description |
|-----|-----------|-------------|
| Bank balance check | Every 4 hours | Wells Fargo checking/savings |
| Credit card balance check | Once daily | All credit card accounts |
| Transaction pull | Once daily | New transactions from all accounts |
| Due date check | Every morning (8 AM) | Alert if payment due within 3 days |
| Weekly spending summary | Sunday 7 PM | Spending breakdown by category |
| Monthly debt report | 1st of month, 9 AM | Progress toward debt payoff goals |
| Heartbeat | Once daily (noon) | "PA running, all systems OK" via Telegram |

**Behavior:**
- Scrape times randomized by +/- 15 minutes
- Failed scrapes retry once after 30 minutes, then alert user
- Jobs don't stack — if previous scrape still running, next one waits
- Configurable via Telegram `/schedule` command

### 6. Telegram Bot (Interface)

**Purpose:** Primary user interface — commands, natural language, and alerts.

**Commands:**
| Command | Description |
|---------|-------------|
| `/unlock` | Enter master password after restart |
| `/lock` | Wipe credentials from memory |
| `/status` | System health, last scrape times, errors |
| `/balance` | Summary of all account balances |
| `/debt` | Total debt broken down by account |
| `/due` | Upcoming due dates and minimum payments |
| `/spending [period]` | Spending breakdown by category |
| `/plan` | Current debt payoff plan and progress |
| `/scrape [institution]` | Force an immediate scrape (all or specific institution) |
| `/schedule [changes]` | View or adjust scrape schedule |
| `/backup` | Trigger an encrypted backup of the database |
| `/help` | List all commands |

**Natural language:** Any non-command message is routed to the Brain for intelligent response. e.g., "how much do I owe Chase?" or "what did I spend on Amazon this month?"

**Proactive alerts:**
- Payment due soon (3 days, 1 day, day-of)
- Scraper failure notifications
- Unusual spending detected
- Weekly/monthly summaries
- System restart / needs unlock
- Daily heartbeat

**Security:**
- Bot only responds to the owner's Telegram user ID (hardcoded during setup)
- All other messages are silently ignored
- Password messages deleted immediately after processing
- No financial data written to bot logs

### 7. Config (Settings Management)

**Purpose:** Centralize all user-configurable settings.

**Storage:** `config.json` file (unencrypted — contains no secrets). Stored alongside the application.

**Settings:**
```json
{
  "telegram_user_id": 123456789,
  "telegram_bot_token_env": "PA_TELEGRAM_TOKEN",
  "claude_api_key_env": "PA_CLAUDE_API_KEY",
  "monthly_income": 5000.00,
  "financial_goals": ["debt-free in 2 years"],
  "preferences": ["don't recommend closing oldest credit card"],
  "schedule": {
    "bank_balance_hours": 4,
    "cc_balance_daily_time": "06:00",
    "transaction_pull_daily_time": "07:00",
    "due_date_check_time": "08:00",
    "weekly_summary_day": "sunday",
    "weekly_summary_time": "19:00"
  },
  "cost_cap_monthly_usd": 20.0,
  "backup_path": "/mnt/usb/pa-backups"
}
```

**Note:** Telegram bot token and Claude API key are stored as environment variables (referenced by name in config). They are set in the systemd service file on the Pi, or in a `.env` file during development (which is in `.gitignore`).

**Interface:**
- `Config.load()` → reads config.json
- `Config.get(key)` → returns a setting value
- `Config.update(key, value)` → updates and persists a setting
- Settings are also editable via Telegram bot commands

### Error Handling Contracts

Each module raises typed exceptions that bubble up to the Bot for user-friendly messaging:

| Module | Exception | Trigger |
|--------|-----------|---------|
| Vault | `VaultAuthError` | Wrong master password |
| Vault | `VaultLockedError` | Operation attempted while locked |
| Scrapers | `ScraperLoginError` | Login failed (wrong creds, site changed) |
| Scrapers | `ScraperMFATimeout` | User didn't provide MFA code within 5 min |
| Scrapers | `ScraperParseError` | Page layout changed, data extraction failed |
| Store | `StoreConnectionError` | Database file missing or corrupt |
| Brain | `BrainAPIError` | Claude API returned error after retries |
| Brain | `BrainCostCapError` | Monthly cost cap exceeded |

The Bot catches all exceptions, logs them to `scrape_log`, and sends a human-readable alert via Telegram. No exceptions crash the main process.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Browser automation | Playwright (Chromium) |
| Database | SQLite + SQLCipher |
| Encryption | cryptography (AES-256-GCM) + argon2-cffi (Argon2id KDF) |
| Async SQLite | aiosqlite + SQLCipher extension |
| Telegram bot | python-telegram-bot |
| Scheduler | APScheduler 4.x (asyncio-native) |
| AI | Claude API (Haiku/Sonnet/Opus tiered) |
| Process manager | systemd (on Raspberry Pi) |

## Deployment

- **Development:** Windows PC (C:\Dev\PA)
- **Production:** Raspberry Pi 5 (4GB), Raspberry Pi OS
- **Deployment method:** SSH + rsync or git pull from private repo
- **Process management:** systemd service with auto-restart on crash
- **Startup flow:**
  1. systemd starts PA on boot
  2. Bot sends Telegram message: "PA restarted. Send /unlock to enter master password."
  3. User sends `/unlock`, enters master password
  4. Vault decrypts, scrapers resume, scheduler starts

## Security Model

1. **No credentials on disk unencrypted** — vault.enc is AES-256-GCM encrypted
2. **No master password stored** — entered at runtime, held in memory only
3. **Database encrypted** — SQLCipher with key from master password
4. **Telegram locked to owner** — only responds to hardcoded user ID
5. **Read-only financial access** — scrapers never click pay/transfer/submit
6. **Message hygiene** — password messages deleted from Telegram immediately
7. **Memory cleanup** — credentials held only while vault is unlocked, zeroed on lock

## Future Expansion (Not in v1)

- Action capabilities with approval gates (bill pay)
- Additional life domains (scheduling, health, etc.)
- Web dashboard for visual charts and reports
- Plaid API integration as alternative to scraping
- Mobile push notifications
- Voice interface
