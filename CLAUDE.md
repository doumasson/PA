# George — Personal Assistant

## Project Overview
A plugin-based personal assistant ("George") with finance as the first plugin. Collects financial data via browser automation, stores it encrypted locally, provides insights/alerts through Telegram — powered by Claude API. Learn-once engine reduces API costs over time.

## Tech Stack
- Python 3.11+
- Playwright (Chromium) for browser automation
- SQLite + SQLCipher for encrypted data storage
- python-telegram-bot for Telegram interface
- APScheduler for job scheduling
- Claude API (Haiku/Sonnet/Opus tiered) for intelligence
- cryptography library (Argon2id + AES-256-GCM) for vault

## Project Structure
```
pa/
  __main__.py              # Entry point (delegates to core/app.py)
  core/                    # Generic infrastructure (domain-agnostic)
    app.py                 # Plugin discovery, wiring, event loop
    identity.py            # George's name/persona (one-file rename)
    config.py              # JSON config loader
    store.py               # Generic SQLite wrapper
    brain.py               # Claude API (generic, plugins add prompt fragments)
    tier.py                # Dynamic tier classifier (plugins register patterns)
    cost_tracker.py        # Monthly API budget
    scheduler.py           # APScheduler (plugins register jobs)
    bot.py                 # Telegram bot (plugins register commands)
    exceptions.py          # Base exception hierarchy
  vault/                   # Credential encryption/decryption
  scrapers/                # Generic scraping infra + learn-once recipe engine
    base.py                # BaseScraper abstract class
    mfa_bridge.py          # Async MFA coordination
    recipe.py              # Learn-once recipe engine
  plugins/
    __init__.py            # PluginBase, Command, Job, AppContext, discover_plugins
    finance/               # Financial tracking plugin
      plugin.py            # FinancePlugin(PluginBase)
      repository.py        # Finance data access layer
      commands.py          # /balance, /debt, /due, /spending, etc.
      formatters.py        # Output formatters
      jobs.py              # Scheduled financial jobs
      schema.sql           # finance_ prefixed tables
      scrapers/            # Bank scrapers (WF, Synchrony, Credit One)
```

## Adding a New Plugin
1. Create `pa/plugins/yourplugin/` with `plugin.py` implementing `PluginBase`
2. Define schema (tables prefixed with plugin name), commands, jobs, tier patterns
3. Export your plugin class from `__init__.py`
4. George discovers it automatically at startup

## Development
- Develop on Windows PC (C:\Dev\PA)
- Deploy to Raspberry Pi 4GB via SSH
- Python virtual environment in `.venv/`

## Commands
- `python -m pa` — Run George
- `python -m pytest` — Run tests

## Security Rules
- NEVER store credentials unencrypted on disk
- NEVER log sensitive data (passwords, balances, account numbers)
- NEVER implement actions that move money (v1 is read-only)
- All database access goes through the core store module
- All credential access goes through the vault module
- Recipe engine only resolves $cred.username and $cred.password (allowlisted)
- Query templates execute on read-only DB connections, SQL validated SELECT-only
- Plugin DDL validated: only CREATE TABLE/INDEX with plugin-prefixed names

## Code Style
- Type hints on all function signatures
- Docstrings on public functions only
- One scraper per file, all extending BaseScraper
- Keep modules loosely coupled — communicate through defined interfaces
- Plugin tables MUST be prefixed with the plugin name (e.g., finance_accounts)
