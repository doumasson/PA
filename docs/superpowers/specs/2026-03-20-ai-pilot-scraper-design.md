# AI Pilot Scraper — Design Spec

## Problem

Hardcoded bank scrapers are unsustainable. Each institution requires manual selector discovery, debugging on Pi hardware, and constant maintenance when sites change. With 10+ financial accounts, this approach doesn't scale.

## Solution

Replace all institution-specific scrapers with a generic AI-driven navigation system ("AI Pilot") that uses Claude to analyze pages and decide what to do, then records successful sequences as recipes for cost-free replay.

## Core Concept

The AI Pilot navigates any banking website the same way a human would — it looks at the page, decides what to do, does it, and looks at the result. It uses cleaned HTML as the primary signal (fast, cheap) and falls back to screenshots when HTML is ambiguous (vision, accurate). No selectors are hardcoded. No per-institution code exists.

## Architecture Overview

```
/scrape wellsfargo
    │
    ▼
Load saved cookies → try direct navigation to accounts page
    │
    ├─ Session valid? → Extract balances (no AI) → Done ($0.00)
    │
    ▼
Load recipe → replay stored action steps
    │
    ├─ Replay succeeds? → Extract balances → mark recipe success → Done ($0.00)
    │
    ▼
AI Pilot takes over (from failure point or from scratch)
    │
    ├─ MFA detected? → Telegram prompt → wait for code → continue
    │
    ▼
Pilot reaches balances → extract data → record new recipe → save cookies → Done
```

**Cost per scrape:**
- Session still valid: $0.00
- Recipe replay works: $0.00
- Recipe breaks, AI re-engages: ~$0.03-0.10
- First-ever scrape: ~$0.05-0.15

## Component Design

### 1. AIPilot (`pa/scrapers/pilot.py`)

The core navigation loop. Institution-agnostic.

**Interface:**
```python
class AIPilot:
    def __init__(self, page: Page, brain: Brain, mfa_bridge: MFABridge):
        ...

    async def run(
        self,
        url: str,
        goal: str,
        credentials: dict[str, str],
        resume_from: list[dict] | None = None,
    ) -> PilotResult:
        ...
```

**PilotResult:**
```python
@dataclass
class PilotResult:
    status: Literal["success", "mfa_needed", "login_failed", "max_steps", "error"]
    balances: list[BalanceData]       # extracted balances (if success)
    actions: list[dict]               # recorded action sequence (for recipe)
    cookies: list[dict]               # browser cookies to persist
    mfa_prompt: str | None            # MFA prompt text (if mfa_needed)
    error: str | None                 # error details
```

**Navigation loop:**
1. Extract cleaned HTML from current page
2. Send to Claude: page HTML + goal + action history so far
3. Claude responds with a structured action (JSON)
4. Execute the action via Playwright
5. Wait for page change (navigation, DOM mutation, or timeout)
6. Loop back to step 1
7. Terminate when Claude returns `extract_balances` action or a terminal signal

**Supported actions from Claude:**
```
fill       — type text into a field: {selector, value}
click      — click an element: {selector}
screenshot — request visual analysis: {reason}
wait       — wait for something: {condition, timeout_ms}
extract    — extract balance data: {balances: [...]}
mfa        — MFA detected: {prompt}
fail       — unrecoverable: {reason}
```

**Credential safety:**
- Claude sees `$cred.username` and `$cred.password` placeholders only
- Pilot substitutes real values at execution time using the same allowlist as the recipe engine
- Real credentials never sent to Claude API

**Guardrails:**
- Max 20 steps per session (prevents infinite loops)
- If page unchanged after action, Claude is told "nothing happened, try different approach"
- 30-second timeout per step
- Random 0.5-2s human-like delays between actions

### 2. Page Analyzer (`pa/scrapers/page_analyzer.py`)

Prepares page content for Claude analysis.

**HTML cleaning:**
- Strip `<script>`, `<style>`, `<noscript>`, `<svg>`, `<path>` tags
- Strip HTML comments
- Remove `data-*` and `aria-*` attributes (noise reduction)
- Keep: forms, inputs, buttons, links, headings, labels, table structures, text content
- Truncate to ~4000 tokens if page is large (keep head/forms/visible text, drop footer/nav noise)

**Screenshot capture:**
- Full page screenshot as PNG
- Viewport set to 1280x720 for consistency
- Used only when Claude requests it (ambiguous HTML) or for checkpoint validation

**Checkpoint hashing:**
- Hash key structural elements of the page (form IDs, heading text, URL path)
- Used by recipe engine to detect when a page has changed enough to invalidate a recipe step

### 3. Session Store (`pa/scrapers/session_store.py`)

Encrypted cookie persistence to minimize logins.

**Storage:**
- Cookies serialized as JSON, encrypted via the vault's encryption (same Argon2id + AES-256-GCM)
- Stored per institution in the vault database
- Cookie expiry respected — expired cookies pruned on load

**Interface:**
```python
class SessionStore:
    def __init__(self, vault: Vault):
        ...

    async def save_cookies(self, institution: str, cookies: list[dict]) -> None:
        ...

    async def load_cookies(self, institution: str) -> list[dict] | None:
        ...

    async def clear_cookies(self, institution: str) -> None:
        ...
```

### 4. Recipe Engine Updates (`pa/scrapers/recipe.py`)

Extend the existing recipe engine:

- **Checkpoint hashes:** Each step stores a hash of the expected page state. During replay, if the hash doesn't match, replay aborts at that step and hands off to Pilot.
- **Resume point:** When handing off to Pilot, pass the step index so Pilot knows what's already been done.
- **Versioning:** Keep up to 3 recipe versions per institution. On Pilot re-engagement, old recipe preserved, new one saved alongside. Oldest version pruned.
- **Schema update:** Bump to version 2 with checkpoint fields.

### 5. MFA Bridge Updates (`pa/scrapers/mfa_bridge.py`)

Enable MFA in subprocess model:

- Subprocess communicates MFA state via stdout JSON protocol
- Main bot process reads subprocess stdout, detects `mfa_needed` message
- Bot sends Telegram message to user with MFA prompt
- User replies with code
- Bot writes code to subprocess stdin (or a temp file the subprocess watches)
- Subprocess reads code, Pilot enters it, continues scraping
- Timeout: 5 minutes for user to provide code

**Subprocess protocol:**
```
Subprocess → Bot:    {"event": "mfa_needed", "prompt": "Enter code sent to ***-1234"}
Bot → Subprocess:    {"event": "mfa_code", "code": "123456"}
Subprocess → Bot:    {"event": "complete", "result": {...}}
```

### 6. Scraper Runner Updates (`pa/plugins/finance/scraper_runner.py`)

Replace hardcoded institution logic with Pilot:

- Remove `_scrape_wellsfargo()` and all institution-specific code
- Initialize AIPilot with browser page and a lightweight Brain instance
- Load cookies → try direct navigation
- If no session: load recipe → replay
- If no recipe or replay fails: Pilot runs from scratch
- MFA communication via stdin/stdout JSON protocol
- On success: output result JSON, recipe data, and cookies

### 7. Commands Updates (`pa/plugins/finance/commands.py`)

Simplify `/scrape` handler:

- Remove institution-specific logic
- Add subprocess MFA handling (read stdout for mfa_needed, send Telegram message, write code to stdin)
- Store returned cookies via SessionStore
- Store returned recipe via RecipeEngine
- Store balances via existing repository

### 8. Files Deleted

- `pa/plugins/finance/scrapers/wellsfargo.py` — replaced by Pilot
- `pa/plugins/finance/scrapers/synchrony.py` — replaced by Pilot
- `pa/plugins/finance/scrapers/credit_one.py` — replaced by Pilot
- `tools/probe_wf.py` — no longer needed

## User Experience

**Adding a new institution:**
```
/addcred mybank
URL: https://mybank.com/login
Username: user123
Password: pass456
```

**Scraping:**
```
/scrape mybank
→ "Scraping mybank... navigating login page"
→ "Logged in. Finding account balances..."
→ "Found 2 accounts:
   Checking ····1234: $1,500.00
   Savings ····5678: $3,200.00
   Recipe saved for future runs."
```

**MFA (when triggered):**
```
/scrape mybank
→ "MFA required: Enter the code sent to ***-1234"
(user replies) 482901
→ "Code accepted. Finding account balances..."
→ "Found 2 accounts: ..."
```

## Claude Prompt Design

The system prompt for the Pilot's Claude calls:

```
You are a browser navigation assistant. You are looking at a web page and deciding what action to take next.

Goal: {goal}

You have these credentials available:
- $cred.username
- $cred.password

Actions taken so far:
{action_history}

Current page URL: {url}
Current page HTML:
{cleaned_html}

Respond with a single JSON action. Available actions:
- {"action": "fill", "selector": "css-selector", "value": "text or $cred.username or $cred.password"}
- {"action": "click", "selector": "css-selector"}
- {"action": "screenshot", "reason": "why you need to see the page visually"}
- {"action": "wait", "condition": "what to wait for", "timeout_ms": 5000}
- {"action": "extract", "balances": [{"account_name": "...", "account_type": "checking|savings|credit_card|mortgage|loan", "balance": 1234.56, "available_credit": ..., "minimum_payment": ..., "due_date": ...}]}
- {"action": "mfa", "prompt": "the MFA prompt shown to the user"}
- {"action": "fail", "reason": "why this cannot proceed"}

Rules:
- Use the most specific CSS selector you can find
- For credential fields, use $cred.username or $cred.password as the value (never guess credentials)
- If the HTML is unclear or you're unsure what you're looking at, request a screenshot
- If you see account balances on the page, extract them immediately
- If you see an MFA/verification code prompt, report it with the mfa action
- If login has clearly failed (wrong password message, locked account), use the fail action
```

## Testing Strategy

- Unit tests for PageAnalyzer (HTML cleaning, truncation, hashing)
- Unit tests for SessionStore (save/load/clear/expiry)
- Unit tests for Recipe v2 (checkpoint hashing, versioning, resume)
- Integration test for Pilot with a mock page (serve a local HTML login form, verify Pilot can navigate it)
- Mock Claude responses in Pilot tests to verify action execution logic

## Security Considerations

- Credentials never sent to Claude — only `$cred.*` placeholders
- Cookies encrypted at rest via vault
- Recipe steps never contain real credential values
- Screenshot images processed in memory, never saved to disk (except debug mode on Pi)
- Subprocess inherits vault unlock state, cannot access other institutions' credentials
