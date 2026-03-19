# Personal Assistant (PA) — Design Spec

## Overview

A personal financial assistant that automatically collects financial data from bank and credit card websites via browser automation, stores it in an encrypted local database, and provides insights, alerts, and debt management advice through a Telegram bot interface — powered by Claude API for intelligent analysis.

**Design philosophy:** Safe, read-only, locally encrypted, extensible. Inspired by OpenClaw's agentic approach but with strict guardrails — the PA observes and advises, it never moves money.

## Architecture

Modular monolith — single Python process with clean internal boundaries.

```
pa/
  __main__.py        # Entry point, wires modules together
  vault/             # Credential encryption/decryption
  scrapers/          # One scraper per financial institution
  store/             # SQLite data layer
  bot/               # Telegram bot interface
  scheduler/         # APScheduler job runner
  brain/             # Claude API integration for analysis
```

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

**Security rules:**
- Decrypted credentials only exist in memory, never on disk
- Memory zeroed after use (best-effort via ctypes)
- No master password stored anywhere
- After reboot, master password must be re-entered via Telegram `/unlock` command
- Both the password message and prompt are deleted from Telegram immediately after processing

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

**MFA handling:**
- When a bank sends an MFA code, the scraper pauses
- Telegram bot asks the user to forward the code
- User replies with the code, scraper resumes
- Most banks remember the device for ~30 days

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

**Encryption:** SQLCipher (encrypted SQLite), key derived from master password.

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
| description | TEXT | Merchant/description |
| amount | REAL | Positive = charge, negative = payment |
| category | TEXT | Auto-assigned by Brain |
| scraped_at | TIMESTAMP | |

**scrape_log**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| institution | TEXT | Which scraper ran |
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

**Auto-tier selection:** Brain classifies incoming queries by complexity and routes to appropriate model.

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
| `/schedule [changes]` | View or adjust scrape schedule |
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

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Browser automation | Playwright (Chromium) |
| Database | SQLite + SQLCipher |
| Encryption | cryptography library (Argon2id + AES-256-GCM) |
| Telegram bot | python-telegram-bot |
| Scheduler | APScheduler |
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
7. **Memory cleanup** — credentials zeroed from memory after use

## Future Expansion (Not in v1)

- Action capabilities with approval gates (bill pay)
- Additional life domains (scheduling, health, etc.)
- Web dashboard for visual charts and reports
- Plaid API integration as alternative to scraping
- Mobile push notifications
- Voice interface
