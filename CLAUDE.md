# Albus — Personal Assistant (v2)

## Project Overview
A self-teaching, self-healing personal assistant on a Raspberry Pi, spoken to via
Telegram. Reflex-first: anything it has handled before replays deterministically at
zero LLM cost; novel requests escalate to Claude via CLIProxyAPI (Max subscription,
localhost:8317 — NEVER the metered API) and every escalation deposits a learned
artifact. Design spec: docs/superpowers/specs/2026-07-02-v2-core-design.md

## Identity
- Name: **Albus**. Warm, wise, Dumbledore-inspired, concise. `pa/core/identity.py`
- Personal data (owner, kids, income, timezone) lives ONLY in untracked
  `config.local.json` → `pa/core/profile.py`. Never hardcode names in source.

## Tech Stack
Python 3.11+ asyncio · python-telegram-bot · APScheduler · SQLite/aiosqlite ·
Argon2id+AES-256-GCM vault · Playwright (AI-pilot scraper) · Teller API ·
OpenAI SDK → CLIProxyAPI (Haiku=parse tier, Sonnet=reason tier)

## Core Architecture (`pa/core/`)
- `kernel.py`   boot + wiring (replaces app.py). data_dir configurable (SSD).
- `brain.py`    THE LLM choke point. Config-driven backends/tiers (Tier.PARSE /
                Tier.REASON), backend fallback, retries, per-context conversations,
                PII scrubbing for untrusted backends, query_json/extract_json.
                Model names appear ONLY in config, never code.
- `reflex.py`   L0 learned-plan replay (zero LLM) → L1 plan-and-learn → chat.
- `learning.py` unified learning store (plans, route rules, preferences, fixes)
                with confidence/hits; bad learnings decay via demote().
- `ledger.py`   error ledger: signature dedup, burst alerts, known-fix lookup.
                NO silent except:pass — record errors here.
- `stats.py`    reflex-rate metrics; /stats shows week-over-week.
- `scrub.py`    PII placeholders on anything leaving for untrusted backends.
- `profile.py`  family profile from config.local.json.
- `bot.py`      Telegram; routes messages through the reflex ladder.
- `scheduler.py` instance-based APScheduler wrapper, ledger-guarded jobs.

## Plugins (`pa/plugins/`) — contract v2
finance (Bart advisor, bills, budgets, AI-pilot scraping) · teller (bank API, mTLS) ·
google (Gmail triage + calendar) · tasks · health · kids · meals · home · research ·
repair (self-repair queue + approval gate). Voice notes are core (pa/core/voice.py).
Backburnered: company plugin (multi-agent workflows) — restore via git tag backburner-company.

Adding a plugin: directory with PluginBase subclass; define schema_sql()/commands()/
jobs()/nl_handlers()/system_prompt_fragment(). Handler signatures are ENFORCED at
boot: commands async(ctx, update, context)->str · NL async(ctx, text, update)->str ·
jobs async(ctx)->None. Tables MUST be prefixed `{plugin}_` and plugins never touch
another plugin's tables. Broken plugins fail the boot loudly (config
plugins.ignore_broken to soften).

## Rules
- LLM calls go through ctx.brain.complete()/query_json() ONLY. Pick Tier.PARSE for
  extraction/classification, Tier.REASON for analysis/advice. No hand-rolled JSON
  parsing of model output.
- Errors: `await ctx.ledger.record(e, source=...)` — never swallow silently.
- Learnings/preferences: ctx.learning (LearningStore), kind-prefixed.
- Credentials only via vault public API (get/add/remove/institutions).
- NEVER store credentials unencrypted, log sensitive data, or implement actions
  that move money (read-only).
- Type hints on signatures; docstrings on public functions; loose coupling.

## Ops
- Pi: 192.168.1.172, ssh admin. Prod worktree ~/pa (master), v2 worktree ~/pa-v2.
- systemd: pa.service (app), cli-proxy-api.service (LLM proxy).
- Tests: `.venv/bin/python -m pytest tests/ -q` — keep green; new core code needs tests.
- Deploy: rsync/git pull to Pi, restart pa.service.
