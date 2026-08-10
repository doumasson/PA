# Albus v2 Core — Design Spec

**Date:** 2026-07-02
**Branch:** `v2` (worktree `~/pa-v2`; `master` keeps serving production until parity)
**Goal:** Rebuild the core so Albus is reflex-first: everything it has seen before is handled
deterministically at zero LLM cost, every escalation teaches the system, every failure is
visible and remembered. Plugins migrate onto this core in Phase 2.

## Design principles

1. **Reflex first.** An LLM call is a cache miss. The router tries learned/deterministic
   handling (L0) before parsing with a cheap model (L1) before reasoning with a strong
   model (L2). Every L1/L2 result must deposit a learned artifact that moves future
   traffic down the ladder.
2. **One choke point.** All LLM traffic flows through `Brain.complete()`. Scrubbing,
   retries, stats, tiering, conversation isolation, and the error ledger hook live there
   and nowhere else.
3. **Backends are config, not code.** Model names never appear in application code.
   Capability tiers (`parse`, `reason`) map to ordered backend/model lists in config.
   Today: CLIProxyAPI (Claude Max). Later: the home-network LLM gets added to config and
   takes over tiers with zero code changes. Backends carry `trusted: bool` — untrusted
   (cloud) backends get scrubbed prompts; the future home LLM is trusted.
4. **Failures are loud, remembered, and eventually self-repairing.** No bare
   `except: pass`. Errors carry signatures into a ledger; known signatures map to
   remembered fixes (Phase 3 automates applying them).
5. **No PII in source or git.** Family details live in a profile section of local config;
   code reads `profile.kids`, never "Maddox".
6. **Plugins are validated at the door.** Wrong handler signature = loud startup error,
   not a silent no-show.

## Modules (`pa/core/`)

### profile.py
`Profile` dataclass loaded from `config.json` `"profile"` section: owner name, kids
(name/birth year/notes), timezone, income, goals. Exposes `system_prompt_fragment()`.
Migration: move `telegram_user_id`, income, goals out of tracked config.json into
untracked `config.local.json` (merged over config.json at load).

### brain.py (rewrite)
- `Backend`: name, base_url, api_key_env, trusted, models: {parse: str, reason: str}.
- `Tier` enum: `PARSE`, `REASON` (the old FAST/STANDARD/DEEP collapse is dead; two real
  tiers, chosen by call sites, with config-ordered fallback across backends).
- `Brain.complete(prompt, *, tier, context_id="main", system=None, json_schema=None)`
  — the choke point: scrub → select backend/model → retry w/ backoff → record stats →
  ledger on failure. Falls back down the backend list on hard errors.
- `Brain.query_json(...)` — THE shared JSON helper (kills 8 copies of boilerplate).
- `BrainContext`: isolated conversation windows keyed by `context_id` (agents get their
  own contexts — this is the AI-company primitive).
- Conversation persistence as today, but per-context.

### scrub.py
`scrub(text) -> (clean_text, restore_map)`: account/card numbers, routing numbers,
exact dollar amounts optionally bucketed, emails/phones → stable placeholders.
Applied in `complete()` when backend is untrusted. `restore(text, map)` on the way out.

### learning.py
Unified learning store, one table `core_learnings`:
`(id, kind, key, value_json, source, confidence, hits, last_used, created_at)`.
Kinds: `plan` (utterance→action plan), `route_rule` (keyword/pattern→intent),
`parse_pattern`, `preference`, `fix` (error signature→remedy), `bill_rule`, etc.
API: `remember(kind, key, value, source)`, `recall(kind, key)`, `similar(kind, text)`,
`confirm(id)` (bump confidence/hits), `demote(id)`, `forget(id)`.
Generalizes agent/memory.py's fixes table + brain's learned plans + preferences.

### reflex.py
L0 router. `route(text) -> Plan | None`:
1. normalized exact-match against learned plans
2. similarity match (Jaccard now, embedding-ready interface)
3. learned route_rules (keywords/patterns taught by L1 decisions)
Returns None on miss → caller escalates to L1 planner, whose output is
`reflex.learn()`-ed. Also `record_outcome(plan_id, ok)` so bad plans decay.

### ledger.py
`record(err, source, context)` → signature = hash(type + normalized message + source).
Dedupe window, escalation policy (first occurrence → Telegram notify; repeats →
count; N repeats in window → "this keeps happening" alert). `known_fix(signature)`
consults learning store kind=fix. All jobs/handlers report here — wrapper provided.

### stats.py
Counters per day: requests handled at L0/L1/L2, tokens in/out per backend, latency,
errors, learnings created. `/stats` renders: reflex rate this week vs last, cost-free
percentage, top escalation reasons. This is the measurable "getting smarter" gauge.

### scheduler.py (rewrite)
Instance-based (no module globals). Same Job dataclass surface, plus per-job ledger
wrapping and last-run/next-run introspection for /status.

### kernel.py
Boot: config+profile → store (data_dir from config — SSD move is a one-line change)
→ learning → ledger → stats → brain → reflex → scheduler → bot → plugins.
Plugin loading: import errors are FATAL at boot with clear message (config flag
`plugins.ignore_broken: true` to soften in emergencies); handler signatures validated
with `inspect.signature` against the contract; `plugins.enabled` allowlist so v2 can
boot with a subset during migration.

### Plugin contract v2 (`pa/plugins/__init__.py`)
- `PluginBase.api_version = 2`; v1 plugins (no attr) rejected with migration hint.
- `nl_handlers()` a real method (no monkey-patch).
- Command handlers: `async (ctx, update, context) -> str`; NL: `async (ctx, text,
  update) -> str`; jobs: `async (ctx) -> None` — enforced at registration.
- `AppContext` gains: `learning`, `ledger`, `profile`, `stats`. Vault/brain accessed
  ONLY via public methods.

### bot.py (port + trim)
Same Telegram surface. `_route_message` becomes: reflex.route() → hit: execute at $0 →
miss: brain plan (L1) → execute → reflex.learn(). Message splitting shared util.
`/stats` command added.

## Testing
- Every core module gets unit tests (fake backend for brain; tmp SQLite for stores).
- The 14 stale George-era tests are replaced along with the modules they tested.
- Live-bot testing needs a second BotFather token (dev bot) — required before Phase 2
  parity runs; ask Steven when Phase 2 starts.

## Out of scope for Phase 1
Plugin ports (Phase 2), Claude Code repair loop (Phase 3), workflow engine (Phase 4).
Vault crypto is kept as-is (drop the ctypes key-zeroing theater; document limitation).
