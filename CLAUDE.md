# Albus — Personal Assistant

## Project Overview
A self-teaching, self-healing personal assistant that runs on a Raspberry Pi and communicates via Telegram. Plugin-based architecture — new features snap in as directories. Uses Claude API with tiered routing (Haiku for cheap queries, Sonnet for analysis, Opus rarely). Encrypted local storage for sensitive data.

## Identity
- Name: **Albus** (not George)
- Persona: Warm, wise, Dumbledore-inspired. Concise and practical.
- Defined in `pa/core/identity.py`

## Tech Stack
- Python 3.11+, async (asyncio)
- python-telegram-bot (Telegram interface)
- APScheduler (scheduled jobs)
- Claude API — Haiku/Sonnet/Opus tiered (low-cost by default)
- SQLite + aiosqlite (data storage)
- cryptography (Argon2id + AES-256-GCM vault)
- Teller API (real-time bank data)

## Project Structure
```
pa/
  __main__.py              # Entry point
  core/                    # Domain-agnostic infrastructure
    app.py                 # Plugin discovery, wiring, event loop
    identity.py            # Name/persona
    config.py              # JSON config loader
    store.py               # SQLite wrapper
    brain.py               # Claude API (tiered, cost-tracked, conversation memory)
    tier.py                # Dynamic tier classifier
    cost_tracker.py        # Monthly API budget (persisted to DB)
    scheduler.py           # APScheduler (plugin-registered jobs)
    bot.py                 # Telegram bot (commands + NL handlers)
    exceptions.py          # Exception hierarchy
  vault/                   # Credential encryption
  scrapers/                # Browser automation
  plugins/
    __init__.py            # PluginBase, Command, Job, NLHandler, discover_plugins
    finance/               # Financial tracking + AI advisor
    google/                # Gmail triage + calendar
    teller/                # Real-time bank data
    agent/                 # DungeonMind build agent control
```

## Adding a New Plugin
1. Create `pa/plugins/yourplugin/__init__.py` with a class extending `PluginBase`
2. Define: `schema_sql()`, `commands()`, `jobs()`, `nl_handlers()`, `system_prompt_fragment()`
3. Tables must be prefixed with plugin name (e.g., `myplugin_items`)
4. Albus discovers it automatically at startup — no wiring needed

## Architecture Principles
- **Self-teaching**: conversation memory, preference learning, interaction tracking
- **Self-healing**: errors logged to DB, repeated failures auto-reported, patterns tracked
- **Low-cost**: Haiku by default for NL queries, Sonnet only when classifier says so
- **Modular**: new feature = new plugin directory, auto-discovered
- **Secure**: vault-encrypted creds, never log sensitive data, read-only financial access

## Security Rules
- NEVER store credentials unencrypted on disk
- NEVER log sensitive data (passwords, balances, account numbers)
- NEVER implement actions that move money (read-only)
- All credential access through vault module
- Plugin DDL validated: only CREATE TABLE/INDEX with plugin-prefixed names

## Code Style
- Type hints on all function signatures
- Docstrings on public functions only
- Keep modules loosely coupled
- Plugin tables MUST be prefixed with the plugin name
