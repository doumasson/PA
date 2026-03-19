# PA — Personal Assistant

## Project Overview
A personal financial assistant that collects financial data via browser automation, stores it encrypted locally, and provides insights/alerts through Telegram — powered by Claude API.

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
  __main__.py        # Entry point
  vault/             # Credential encryption/decryption
  scrapers/          # One scraper per financial institution
  store/             # SQLite data layer
  bot/               # Telegram bot interface
  scheduler/         # APScheduler job runner
  brain/             # Claude API integration
```

## Development
- Develop on Windows PC (C:\Dev\PA)
- Deploy to Raspberry Pi 5 via SSH
- Python virtual environment in `.venv/`

## Commands
- `python -m pa` — Run the PA
- `python -m pytest` — Run tests

## Security Rules
- NEVER store credentials unencrypted on disk
- NEVER log sensitive data (passwords, balances, account numbers)
- NEVER implement actions that move money (v1 is read-only)
- All database access goes through the store module
- All credential access goes through the vault module

## Code Style
- Type hints on all function signatures
- Docstrings on public functions only
- One scraper per file, all extending BaseScraper
- Keep modules loosely coupled — communicate through defined interfaces
