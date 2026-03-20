# PA Plugin Architecture & Learn-Once Engine — Design Spec

**Goal:** Refactor PA from a hardcoded financial assistant into a generic personal assistant ("George") with a plugin system. Finance becomes the first plugin. Add a learn-once-replay engine so George gets cheaper to run over time.

**Builds on:** `docs/superpowers/specs/2026-03-19-personal-assistant-design.md`

---

## 1. Identity

George's name and personality live in a single file (`pa/core/identity.py`). Every module that references the assistant's name imports from here. Renaming is a one-file change.

```python
# pa/core/identity.py
NAME = "George"
GREETING = f"Hey, {NAME} here."
PERSONA = (
    f"{NAME} is a personal assistant. "
    "Helpful, concise, and proactive. "
    "Speaks casually but knows his stuff."
)
```

The Telegram bot display name is configured separately via BotFather but George refers to himself using `NAME`.

---

## 2. Plugin Architecture

### 2.1 Directory Structure

```
pa/
  core/                        # Generic infrastructure (domain-agnostic)
    __init__.py
    app.py                     # Entry point — discovers plugins, wires modules
    identity.py                # George's name, greeting, persona
    config.py                  # JSON config loader (from existing config module)
    store.py                   # SQLite wrapper (from existing store module)
    brain.py                   # Claude API integration (from existing brain module)
    cost_tracker.py            # Monthly budget enforcement
    tier.py                    # Query tier classifier (base + plugin patterns)
    scheduler.py               # APScheduler wrapper (from existing scheduler module)
    bot.py                     # Telegram bot (from existing bot module)
    exceptions.py              # Base exception hierarchy
  vault/                       # Credential encryption (any plugin can use)
    __init__.py
    vault.py
    crypto.py
  scrapers/                    # Generic scraping infrastructure
    __init__.py
    base.py                    # BaseScraper abstract class
    mfa_bridge.py              # Async MFA coordination
    recipe.py                  # Learn-once recipe engine (NEW)
  plugins/
    __init__.py                # Plugin discovery and registry
    finance/                   # First plugin — all financial functionality
      __init__.py              # Exports FinancePlugin
      plugin.py                # Plugin protocol implementation
      schema.sql               # Finance tables (accounts, balances, transactions, merchant_categories)
      commands.py              # /balance, /debt, /due, /spending, /plan command handlers
      jobs.py                  # Scheduled financial jobs (scrape, alerts, summaries)
      formatters.py            # Balance/debt/spending/due formatters
      tier_patterns.py         # Financial keyword patterns for tier classification
      scrapers/                # Finance-specific scrapers
        __init__.py
        wellsfargo.py
        synchrony.py
        credit_one.py
tests/
  core/                        # Core module tests
    test_config.py
    test_store.py
    test_brain.py
    test_cost_tracker.py
    test_tier.py
    test_scheduler.py
    test_bot.py
    test_identity.py
    test_recipe.py
    test_plugin_registry.py
  vault/                       # Vault tests
    test_vault.py
    test_vault_crypto.py
  plugins/
    finance/                   # Finance plugin tests
      test_commands.py
      test_formatters.py
      test_jobs.py
      test_tier_patterns.py
      test_merchant_categories.py
      test_scraper_base.py
  test_mfa_bridge.py
  test_integration.py
  conftest.py
```

### 2.2 Plugin Protocol

Every plugin implements this interface:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class Command:
    """A bot command registered by a plugin."""
    name: str                  # "balance" (without /)
    description: str           # "Show account balances"
    handler: Callable          # async def handler(context) -> str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Job:
    """A scheduled job registered by a plugin."""
    name: str                  # "bank_balance"
    handler: Callable          # async def handler() -> None
    trigger: str               # "interval" or "cron"
    kwargs: dict[str, Any] = field(default_factory=dict)  # trigger kwargs


class Plugin:
    """Base class for all PA plugins."""

    name: str                          # "finance"
    description: str                   # "Financial tracking and insights"
    version: str = "0.1.0"

    def schema_sql(self) -> str:
        """Return DDL for this plugin's tables. Called once at startup."""
        return ""

    def commands(self) -> list[Command]:
        """Return bot commands this plugin provides."""
        return []

    def jobs(self) -> list[Job]:
        """Return scheduled jobs this plugin needs."""
        return []

    def tier_patterns(self) -> dict[str, list[str]]:
        """Return keyword patterns for brain tier classification.
        Keys: 'fast', 'standard', 'deep'. Values: regex pattern lists."""
        return {}

    def system_prompt_fragment(self) -> str:
        """Return this plugin's contribution to George's system prompt.
        Combined with identity persona and other plugins' fragments."""
        return ""

    async def on_startup(self, app: Any) -> None:
        """Called after all modules are initialized. Plugin can grab refs it needs."""
        pass

    async def on_shutdown(self) -> None:
        """Called during graceful shutdown."""
        pass
```

### 2.3 Plugin Discovery

`pa/plugins/__init__.py` scans all subdirectories of `pa/plugins/` for modules that export a `Plugin` subclass. Registration order is alphabetical by plugin name. Each plugin's `schema_sql()` runs during store initialization.

```python
# pa/plugins/__init__.py
def discover_plugins() -> list[Plugin]:
    """Scan pa/plugins/ subdirectories, import each, collect Plugin subclasses."""
    ...
```

### 2.4 Core Wiring (app.py)

The entry point (`pa/core/app.py`, replacing `pa/__main__.py`) does:

1. Load config
2. Initialize core modules (store, vault, brain, scheduler, bot)
3. Discover plugins via `discover_plugins()`
4. For each plugin:
   - Run `schema_sql()` against store
   - Register `commands()` with bot
   - Register `jobs()` with scheduler
   - Merge `tier_patterns()` into tier classifier
   - Append `system_prompt_fragment()` to brain's prompt builder
   - Call `on_startup(app)`
5. Start bot + scheduler
6. Wait for shutdown signal
7. Call `on_shutdown()` on each plugin, then tear down core

### 2.5 Bot Command Routing

The core bot maintains a command registry (`dict[str, Command]`). Plugins register commands at startup. When a message arrives:

1. Auth check (single user ID from config)
2. If command (`/something`): look up in registry, dispatch to plugin handler
3. If password/MFA input: route to vault/mfa_bridge (core responsibility)
4. If free-form text: check query template cache (Section 3), else route to brain

Core owns a few built-in commands that no plugin can override:
- `/unlock`, `/lock` — vault management
- `/status` — system status (uptime, plugin list, cost this month)
- `/help` — auto-generated from all registered commands
- `/plugins` — list active plugins

### 2.6 Scheduler Job Routing

Same pattern — plugins register jobs, core scheduler manages execution. Core keeps only `heartbeat` as a built-in job.

---

## 3. Learn-Once-Replay Engine

### 3.1 Scraper Recipes

A recipe is a recorded sequence of browser actions that can be replayed without AI assistance.

**Core tables** (in store, not plugin-specific — any plugin can use scrapers):

```sql
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin TEXT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    steps TEXT NOT NULL,              -- JSON array of action objects
    version INTEGER NOT NULL DEFAULT 1,
    last_success TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**Recipe step format:**

```json
[
    {"action": "goto", "url": "https://..."},
    {"action": "fill", "selector": "#username", "value": "$cred.username"},
    {"action": "fill", "selector": "#password", "value": "$cred.password"},
    {"action": "click", "selector": "button[type=submit]"},
    {"action": "wait", "state": "networkidle"},
    {"action": "read", "selector": ".balance-amount", "store_as": "balance"},
    {"action": "read_table", "selector": ".transactions tbody tr", "store_as": "transactions"}
]
```

Special `$cred.*` variables are resolved from the vault at runtime. No credentials stored in recipes.

**Recipe engine flow (`pa/scrapers/recipe.py`):**

```python
class RecipeEngine:
    async def has_recipe(self, name: str) -> bool: ...
    async def replay(self, name: str, page, credentials: dict) -> dict[str, Any]: ...
    async def record(self, name: str, plugin: str, steps: list[dict]) -> None: ...
    async def mark_stale(self, name: str) -> None: ...
```

**Scraper integration:**

Each scraper's `get_balances()` and `get_transactions()` methods:
1. Check for existing recipe via `recipe_engine.has_recipe()`
2. If recipe exists: `replay()` it. If replay fails (selector not found, timeout): `mark_stale()`, fall through to step 3
3. If no recipe or stale: use AI-assisted scraping — Claude examines page HTML, identifies elements, guides Playwright. Record successful steps as new recipe.

AI-assisted scraping uses the brain module with a specialized prompt that returns structured step data. This costs one API call per recipe creation/rebuild.

### 3.2 Query Templates

Cached patterns for repeated questions so George can answer without API calls.

**Core table:**

```sql
CREATE TABLE IF NOT EXISTS query_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,       -- regex matching user input
    sql_template TEXT NOT NULL,         -- parameterized SQL query
    format_template TEXT NOT NULL,      -- Python format string for response
    plugin TEXT NOT NULL,               -- which plugin created this
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**Flow:**

1. User sends free-form question
2. Core checks all `query_templates` — if pattern matches, execute SQL directly, format response, return (zero API cost)
3. On cache miss: send to Brain. Brain response includes optional `__template` metadata block:
   ```json
   {"pattern": "total (credit card |)debt", "sql": "SELECT ...", "format": "Your total debt is ${total:,.2f}"}
   ```
4. If template metadata present, save to `query_templates`
5. Template hits increment `hit_count` for analytics

**Template invalidation:** If a template's SQL returns an error (schema changed), the template is deleted and the question falls through to AI.

### 3.3 Merchant Categorization (Finance Plugin)

Finance plugin table:

```sql
CREATE TABLE IF NOT EXISTS merchant_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,      -- normalized merchant name ("CHICK-FIL-A")
    category TEXT NOT NULL,            -- "Food > Dining Out"
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL DEFAULT 'ai', -- 'ai' or 'user'
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**Categorization flow:**

1. New transactions arrive from scraper
2. Normalize merchant name (strip store numbers, trailing digits, whitespace)
3. Look up in `merchant_categories` — cache hit? Apply category directly
4. Collect uncategorized merchants into batches (up to 50)
5. Send batch to Brain: "Categorize these merchants: [list]"
6. Parse response, insert into `merchant_categories`
7. User can override via `/categorize MERCHANT as CATEGORY` — saved with `source='user'`, always takes precedence

**Category hierarchy:** Use `>` separator for nested categories (e.g., `Food > Groceries`, `Food > Dining Out`, `Transport > Gas`, `Shopping > Amazon`). This enables both granular and rolled-up spending views.

---

## 4. Finance Plugin Detail

The finance plugin (`pa/plugins/finance/`) encapsulates everything financial:

### 4.1 Schema (`schema.sql`)

Moves existing tables here:
- `accounts` (id, institution, name, type, interest_rate, credit_limit)
- `balances` (account_id, balance, statement_balance, available_credit, minimum_payment, due_date)
- `transactions` (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending)
- `scrape_log` (institution, account_id, status, error_message, duration_seconds)
- `merchant_categories` (pattern, category, confidence, source, hit_count)

### 4.2 Commands (`commands.py`)

Registers: `/balance`, `/debt`, `/due`, `/spending`, `/plan`, `/scrape`, `/schedule`, `/backup`

Each handler receives a context object with access to store, vault, brain, and config.

### 4.3 Jobs (`jobs.py`)

Registers:
- `bank_balance` — interval, every 4 hours
- `cc_balance` — cron, daily 6 AM
- `transaction_pull` — cron, daily 7 AM
- `due_date_check` — cron, daily 8 AM
- `weekly_summary` — cron, Sunday 7 PM
- `monthly_report` — cron, 1st at 9 AM
- `categorize_pending` — cron, daily after transaction_pull (NEW — batch categorize uncategorized transactions)

### 4.4 System Prompt Fragment

```
You are George's financial analysis module. You have access to bank accounts,
credit cards, and transaction data. Help the user understand their spending,
track debt payoff progress, and make smart financial decisions. Be specific
with numbers. Flag concerning patterns proactively.
```

### 4.5 Tier Patterns

- **FAST**: balance, due, minimum payment, account list
- **STANDARD**: spending analysis, categorization, monthly summary
- **DEEP**: debt payoff strategies, financial planning, anomaly investigation

---

## 5. Migration Strategy

This is a refactor of existing working code, not a rewrite. The approach:

1. Create `pa/core/` and move generic modules there (config, store, brain, scheduler, bot, exceptions)
2. Create `pa/core/identity.py` with George's name
3. Create plugin protocol and registry in `pa/plugins/__init__.py`
4. Create `pa/plugins/finance/` and move financial logic there
5. Create `pa/scrapers/recipe.py` (learn-once engine)
6. Add recipe and query_template tables to core schema
7. Rewire `pa/__main__.py` → `pa/core/app.py`
8. Update all imports across codebase
9. Restructure tests to mirror new layout
10. Verify all 67+ tests still pass

No functionality changes — same features, better architecture.

---

## 6. Security Rules (Unchanged)

- All credentials through vault only
- No sensitive data in logs
- Read-only v1 — no money movement
- Recipe steps use `$cred.*` variables, never raw credentials
- Query templates execute parameterized SQL only (no string interpolation)
- Single-user auth on all bot commands

---

## 7. Future Plugin Ideas (Not Built Now)

Documented to validate the plugin architecture handles diverse use cases:
- **Health** — Apple Health sync, medication reminders, fitness tracking
- **Home** — Smart home integration, energy usage, utility tracking
- **Tasks** — Todo lists, habit tracking, goal management
- **Shopping** — Price tracking, deal alerts, wishlist management
- **Calendar** — Schedule management, appointment reminders

Each would follow the same pattern: `plugin.py` implementing the Protocol, own schema, own commands, own jobs.
