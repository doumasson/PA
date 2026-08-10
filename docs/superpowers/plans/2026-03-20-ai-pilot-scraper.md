# AI Pilot Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all hardcoded bank scrapers with an AI-driven navigation system that figures out how to scrape any banking site given just a URL and credentials.

**Architecture:** A generic AIPilot class sends cleaned HTML (and optionally screenshots) to Claude, which responds with structured navigation actions. Successful action sequences are recorded as recipes for cost-free replay. Cookies are persisted to skip login when sessions are still valid. MFA is handled via subprocess stdin/stdout protocol with Telegram relay.

**Tech Stack:** Python 3.11+, Playwright (Chromium), Claude API (Sonnet for navigation), SQLite, python-telegram-bot

**Spec:** `docs/superpowers/specs/2026-03-20-ai-pilot-scraper-design.md`

---

### Task 1: Page Analyzer — HTML Cleaning and Screenshots

**Files:**
- Create: `pa/scrapers/page_analyzer.py`
- Create: `tests/scrapers/test_page_analyzer.py`

- [ ] **Step 1: Write failing tests for HTML cleaning**

```python
# tests/scrapers/test_page_analyzer.py
import pytest
from pa.scrapers.page_analyzer import clean_html, compute_page_hash


class TestCleanHtml:
    def test_strips_script_tags(self):
        html = '<html><body><script>alert("x")</script><p>Hello</p></body></html>'
        result = clean_html(html)
        assert "alert" not in result
        assert "Hello" in result

    def test_strips_style_tags(self):
        html = "<html><body><style>.x{color:red}</style><p>Hello</p></body></html>"
        result = clean_html(html)
        assert "color" not in result
        assert "Hello" in result

    def test_strips_noscript_svg_path(self):
        html = "<html><body><noscript>no</noscript><svg><path d='M0'/></svg><p>Hi</p></body></html>"
        result = clean_html(html)
        assert "noscript" not in result.lower()
        assert "<svg" not in result.lower()
        assert "Hi" in result

    def test_strips_html_comments(self):
        html = "<html><body><!-- secret --><p>Visible</p></body></html>"
        result = clean_html(html)
        assert "secret" not in result
        assert "Visible" in result

    def test_preserves_forms_inputs_buttons(self):
        html = '<html><body><form><input id="user" type="text"/><button>Login</button></form></body></html>'
        result = clean_html(html)
        assert "input" in result
        assert "button" in result.lower()
        assert "Login" in result

    def test_preserves_links_and_headings(self):
        html = '<html><body><h1>Welcome</h1><a href="/accounts">My Accounts</a></body></html>'
        result = clean_html(html)
        assert "Welcome" in result
        assert "My Accounts" in result

    def test_truncates_large_html(self):
        html = "<html><body>" + "<p>Line</p>" * 5000 + "</body></html>"
        result = clean_html(html, max_chars=2000)
        assert len(result) <= 2500  # some buffer for truncation message

    def test_removes_data_attributes(self):
        html = '<html><body><div data-analytics="track" data-id="123"><p>Content</p></div></body></html>'
        result = clean_html(html)
        assert "data-analytics" not in result
        assert "data-id" not in result
        assert "Content" in result


class TestComputePageHash:
    def test_same_content_same_hash(self):
        h1 = compute_page_hash("https://bank.com/login", "Welcome to bank login")
        h2 = compute_page_hash("https://bank.com/login", "Welcome to bank login")
        assert h1 == h2

    def test_different_url_different_hash(self):
        h1 = compute_page_hash("https://bank.com/login", "Welcome")
        h2 = compute_page_hash("https://bank.com/accounts", "Welcome")
        assert h1 != h2

    def test_different_text_different_hash(self):
        h1 = compute_page_hash("https://bank.com/login", "Welcome")
        h2 = compute_page_hash("https://bank.com/login", "Dashboard")
        assert h1 != h2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scrapers/test_page_analyzer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pa.scrapers.page_analyzer'`

- [ ] **Step 3: Implement page_analyzer.py**

```python
# pa/scrapers/page_analyzer.py
"""HTML cleaning and page analysis utilities for AI Pilot."""

import hashlib
import re


# Tags to strip entirely (including content)
_STRIP_TAGS = re.compile(
    r"<(script|style|noscript|svg|path)\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)

# HTML comments
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)

# data-* and aria-* attributes
_DATA_ATTRS = re.compile(r'\s(?:data-|aria-)\w+(?:=(?:"[^"]*"|\'[^\']*\'|\S+))?', re.IGNORECASE)

# Self-closing tags to strip (svg, path without closing tags)
_SELF_CLOSING_STRIP = re.compile(r"<(?:svg|path)\b[^/>]*/?>", re.IGNORECASE)


def clean_html(html: str, max_chars: int = 12000) -> str:
    """Strip noise from HTML, keeping forms/inputs/buttons/links/text.

    Returns cleaned HTML truncated to max_chars if needed.
    """
    result = _STRIP_TAGS.sub("", html)
    result = _SELF_CLOSING_STRIP.sub("", result)
    result = _COMMENTS.sub("", result)
    result = _DATA_ATTRS.sub("", result)

    # Collapse excessive whitespace
    result = re.sub(r"\n\s*\n", "\n", result)
    result = result.strip()

    if len(result) > max_chars:
        result = result[:max_chars] + "\n[...truncated...]"

    return result


def compute_page_hash(url: str, visible_text: str) -> str:
    """Hash URL + visible text for checkpoint comparison."""
    content = f"{url}|{visible_text}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def extract_visible_text(page) -> str:
    """Extract visible text content from a Playwright page."""
    return await page.evaluate("() => document.body.innerText || ''")


async def take_screenshot(page) -> bytes:
    """Take a PNG screenshot of the current page."""
    return await page.screenshot(type="png", full_page=False)


async def get_cleaned_html(page) -> str:
    """Get the page HTML and clean it for Claude analysis."""
    html = await page.content()
    return clean_html(html)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scrapers/test_page_analyzer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add pa/scrapers/page_analyzer.py tests/scrapers/test_page_analyzer.py
git commit -m "feat: add page analyzer for HTML cleaning and page hashing"
```

---

### Task 2: Session Store — Encrypted Cookie Persistence

**Files:**
- Create: `pa/scrapers/session_store.py`
- Create: `tests/scrapers/test_session_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/scrapers/test_session_store.py
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from pa.scrapers.session_store import SessionStore


@pytest.fixture
def mock_vault():
    vault = MagicMock()
    vault.is_unlocked = True
    vault._data = {}
    vault._save = AsyncMock()
    return vault


@pytest.fixture
def store(mock_vault):
    return SessionStore(mock_vault)


class TestSessionStore:
    @pytest.mark.asyncio
    async def test_save_and_load_cookies(self, store, mock_vault):
        cookies = [{"name": "session", "value": "abc123", "domain": ".bank.com"}]
        await store.save_cookies("wellsfargo", cookies)
        loaded = await store.load_cookies("wellsfargo")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["name"] == "session"

    @pytest.mark.asyncio
    async def test_load_returns_none_when_no_cookies(self, store):
        result = await store.load_cookies("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_cookies(self, store, mock_vault):
        await store.save_cookies("wellsfargo", [{"name": "s", "value": "v"}])
        await store.clear_cookies("wellsfargo")
        result = await store.load_cookies("wellsfargo")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_cookies_pruned(self, store, mock_vault):
        cookies = [
            {"name": "good", "value": "v", "expires": time.time() + 3600},
            {"name": "expired", "value": "v", "expires": time.time() - 3600},
        ]
        await store.save_cookies("bank", cookies)
        loaded = await store.load_cookies("bank")
        assert len(loaded) == 1
        assert loaded[0]["name"] == "good"

    @pytest.mark.asyncio
    async def test_cookies_without_expires_kept(self, store, mock_vault):
        cookies = [{"name": "session", "value": "v"}]
        await store.save_cookies("bank", cookies)
        loaded = await store.load_cookies("bank")
        assert len(loaded) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scrapers/test_session_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement session_store.py**

```python
# pa/scrapers/session_store.py
"""Encrypted cookie persistence for browser sessions."""

import json
import time
from typing import Any


# Prefixed with _ to signal internal use; /creds handler filters this out
_SESSIONS_KEY = "_sessions"


class SessionStore:
    """Stores browser cookies in the vault, encrypted at rest.

    Cookies are stored under the _SESSIONS_KEY in the vault data dict.
    The /creds command must filter this key out to avoid showing it as an institution.
    """

    def __init__(self, vault: Any):
        self._vault = vault

    def _get_sessions(self) -> dict[str, Any]:
        return self._vault._data.get(_SESSIONS_KEY, {})

    async def save_cookies(self, institution: str, cookies: list[dict]) -> None:
        sessions = self._get_sessions()
        sessions[institution] = cookies
        self._vault._data[_SESSIONS_KEY] = sessions
        await self._vault._save()

    async def load_cookies(self, institution: str) -> list[dict] | None:
        sessions = self._get_sessions()
        cookies = sessions.get(institution)
        if cookies is None:
            return None
        # Prune expired cookies
        now = time.time()
        valid = [c for c in cookies if c.get("expires", now + 1) > now]
        if not valid:
            return None
        return valid

    async def clear_cookies(self, institution: str) -> None:
        sessions = self._get_sessions()
        sessions.pop(institution, None)
        self._vault._data[_SESSIONS_KEY] = sessions
        await self._vault._save()
```

**Important:** The `/creds` handler in `pa/core/bot.py` (line 177) iterates `self._vault._data`. After this change, it will show `_sessions` as an institution. Update `_handle_creds` to filter it out:

```python
    async def _handle_creds(self, update, context):
        # ... existing auth/unlock checks ...
        creds = {k: v for k, v in self._vault._data.items() if not k.startswith("_")}
        # ... rest unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scrapers/test_session_store.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add pa/scrapers/session_store.py tests/scrapers/test_session_store.py
git commit -m "feat: add encrypted session store for cookie persistence"
```

---

### Task 3: Brain.query_json() — Structured API Responses with Vision

**Files:**
- Modify: `pa/core/brain.py`
- Modify: `tests/core/test_brain.py`

- [ ] **Step 1: Write failing tests for query_json**

Add to `tests/core/test_brain.py`:

```python
class TestQueryJson:
    @pytest.mark.asyncio
    async def test_query_json_returns_parsed_dict(self, brain, mock_client):
        mock_client.messages.create.return_value = _mock_response('{"action": "click", "selector": "#btn"}')
        result = await brain.query_json("navigate this page", system_prompt="You are a navigator")
        assert result == {"action": "click", "selector": "#btn"}

    @pytest.mark.asyncio
    async def test_query_json_extracts_json_from_markdown(self, brain, mock_client):
        mock_client.messages.create.return_value = _mock_response(
            'Here is the action:\n```json\n{"action": "fill", "selector": "#user"}\n```'
        )
        result = await brain.query_json("navigate", system_prompt="nav")
        assert result == {"action": "fill", "selector": "#user"}

    @pytest.mark.asyncio
    async def test_query_json_skips_rate_limit(self, brain, mock_client):
        mock_client.messages.create.return_value = _mock_response('{"action": "click"}')
        # Fill rate limit
        for _ in range(30):
            brain._query_timestamps.append(time.monotonic())
        # Should NOT raise — query_json is exempt
        result = await brain.query_json("nav", system_prompt="nav")
        assert result == {"action": "click"}

    @pytest.mark.asyncio
    async def test_query_json_with_image(self, brain, mock_client):
        mock_client.messages.create.return_value = _mock_response('{"action": "click", "selector": "#login"}')
        result = await brain.query_json(
            "what should I click?",
            system_prompt="nav",
            image=b"\x89PNG\r\n\x1a\n",
        )
        assert result["action"] == "click"
        # Verify image was sent in the message
        call_args = mock_client.messages.create.call_args
        content = call_args.kwargs["messages"][0]["content"]
        assert any(block.get("type") == "image" for block in content)
```

Note: you'll need to add `import time` at the top if not present, and ensure `_mock_response` helper exists. Check the existing test file for the fixture pattern used.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/test_brain.py::TestQueryJson -v`
Expected: FAIL — `AttributeError: 'Brain' object has no attribute 'query_json'`

- [ ] **Step 3: Add query_json method to Brain**

Add after the existing `query` method in `pa/core/brain.py`:

```python
    async def query_json(
        self,
        user_message: str,
        system_prompt: str,
        tier: Tier = Tier.STANDARD,
        image: bytes | None = None,
        max_tokens: int = 1024,
    ) -> dict:
        """Send a query expecting a JSON response. Skips rate limit (infrastructure use).

        If image is provided, sends it as a vision message alongside the text.
        Extracts JSON from the response, handling markdown code blocks.
        """
        model = self.select_model(tier)

        estimated_cost = _COST_PER_1K_TOKENS[tier] * 2
        self._cost_tracker.check_budget(estimated_cost)

        # Build message content
        if image is not None:
            import base64
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image).decode(),
                    },
                },
                {"type": "text", "text": user_message},
            ]
        else:
            content = user_message

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": content}],
                )
                break
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
        else:
            raise BrainAPIError(f"Claude API error after {_MAX_RETRIES} retries: {last_error}") from last_error

        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        actual_cost = (total_tokens / 1000) * _COST_PER_1K_TOKENS[tier]
        self._cost_tracker.record(actual_cost)

        text = response.content[0].text
        return self._extract_json(text)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from response text, handling markdown code blocks."""
        import json as json_mod
        import re

        # Try to find JSON in markdown code block first
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return json_mod.loads(match.group(1).strip())

        # Try parsing the whole text as JSON
        stripped = text.strip()
        # Find first { and last }
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1:
            return json_mod.loads(stripped[start : end + 1])

        raise ValueError(f"No valid JSON found in response: {text[:200]}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/core/test_brain.py -v`
Expected: All PASS (existing + new tests)

- [ ] **Step 5: Commit**

```bash
git add pa/core/brain.py tests/core/test_brain.py
git commit -m "feat: add Brain.query_json() for structured responses with vision"
```

---

### Task 4: Recipe Engine v2 — Checkpoint Hashing, Replay Executor

**Files:**
- Modify: `pa/scrapers/recipe.py`
- Modify: `tests/core/test_recipe.py`

- [ ] **Step 1: Write failing tests for v2 features**

Add to `tests/core/test_recipe.py` (use existing `engine` fixture — no `store` param needed):

```python
class TestRecipeV2:
    @pytest.mark.asyncio
    async def test_checkpoint_stored_in_steps(self, engine):
        steps = [
            {"action": "fill", "selector": "#user", "value": "$cred.username", "checkpoint": "abc123"},
            {"action": "click", "selector": "#submit", "checkpoint": "def456"},
        ]
        await engine.record("login_bank", "finance", steps)
        recipe = await engine.get_recipe("login_bank")
        assert recipe is not None
        parsed_steps = json.loads(recipe["steps"])
        assert parsed_steps[0]["checkpoint"] == "abc123"

    @pytest.mark.asyncio
    async def test_record_overwrites_same_name(self, engine):
        for i in range(5):
            await engine.record("login_bank", "finance", [{"action": "click", "selector": f"#btn{i}"}])
        recipe = await engine.get_recipe("login_bank")
        parsed = json.loads(recipe["steps"])
        assert parsed[0]["selector"] == "#btn4"

    @pytest.mark.asyncio
    async def test_schema_version_2(self, engine):
        await engine.record("login_bank", "finance", [{"action": "click", "selector": "#btn"}])
        recipe = await engine.get_recipe("login_bank")
        assert recipe["schema_version"] >= 2


class TestRecipeReplay:
    @pytest.mark.asyncio
    async def test_replay_executes_steps(self, engine):
        """Test replay returns steps resolved with credentials."""
        steps = [
            {"action": "fill", "selector": "#user", "value": "$cred.username", "checkpoint": "abc"},
            {"action": "fill", "selector": "#pass", "value": "$cred.password", "checkpoint": "def"},
            {"action": "click", "selector": "#submit", "checkpoint": "ghi"},
        ]
        await engine.record("login_bank", "finance", steps)
        resolved = await engine.get_replay_steps("login_bank", {"username": "john", "password": "secret"})
        assert resolved is not None
        assert len(resolved) == 3
        assert resolved[0]["resolved_value"] == "john"
        assert resolved[1]["resolved_value"] == "secret"
        assert resolved[2].get("resolved_value") is None  # click has no value

    @pytest.mark.asyncio
    async def test_replay_returns_none_for_missing_recipe(self, engine):
        result = await engine.get_replay_steps("nonexistent", {"username": "u", "password": "p"})
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/test_recipe.py::TestRecipeV2 tests/core/test_recipe.py::TestRecipeReplay -v`
Expected: FAIL

- [ ] **Step 3: Update recipe.py for v2 with replay support**

Update `CURRENT_SCHEMA_VERSION` to `2` and add `get_replay_steps` method to `RecipeEngine`:

```python
    async def get_replay_steps(
        self, name: str, credentials: dict[str, str]
    ) -> list[dict[str, Any]] | None:
        """Get recipe steps resolved with credentials, ready for replay.

        Each step gets a 'resolved_value' key with the actual credential value
        substituted (for fill actions). Returns None if no recipe found.
        """
        recipe = await self.get_recipe(name)
        if recipe is None:
            return None
        steps = json.loads(recipe["steps"])
        resolved = self.resolve_credentials(steps, credentials)
        # Add resolved_value for fill actions
        for step in resolved:
            if step.get("action") == "fill" and "value" in step:
                step["resolved_value"] = step["value"]
            else:
                step["resolved_value"] = None
        return resolved
```

- [ ] **Step 4: Run all recipe tests**

Run: `python -m pytest tests/core/test_recipe.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add pa/scrapers/recipe.py tests/core/test_recipe.py
git commit -m "feat: bump recipe engine to v2 with checkpoint and replay support"
```

---

### Task 5: AI Pilot — Core Navigation Loop

**Files:**
- Create: `pa/scrapers/pilot.py`
- Create: `tests/scrapers/test_pilot.py`

This is the largest task. The Pilot is the core of the system.

- [ ] **Step 1: Write failing tests for PilotResult and action execution**

```python
# tests/scrapers/test_pilot.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pa.scrapers.pilot import AIPilot, PilotResult, ScrapedAccount, PILOT_SYSTEM_PROMPT


class TestScrapedAccount:
    def test_create_minimal(self):
        a = ScrapedAccount(account_name="Checking", account_type="checking", balance=1500.0)
        assert a.balance == 1500.0
        assert a.available_credit is None

    def test_create_full(self):
        a = ScrapedAccount(
            account_name="Visa ****1234",
            account_type="credit_card",
            balance=500.0,
            available_credit=4500.0,
            minimum_payment=25.0,
            due_date="2026-04-15",
        )
        assert a.minimum_payment == 25.0


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = "https://bank.com/login"
    page.content = AsyncMock(return_value="<html><body><form><input id='user'/></form></body></html>")
    page.evaluate = AsyncMock(return_value="Login page")
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG")
    return page


@pytest.fixture
def mock_brain():
    brain = AsyncMock()
    return brain


@pytest.fixture
def pilot(mock_page, mock_brain):
    return AIPilot(mock_page, mock_brain)


class TestPilotActionExecution:
    @pytest.mark.asyncio
    async def test_fill_action_substitutes_credentials(self, pilot, mock_page, mock_brain):
        # Claude says fill username, then extract
        mock_brain.query_json = AsyncMock(side_effect=[
            {"action": "fill", "selector": "#user", "value": "$cred.username"},
            {"action": "extract", "balances": [{"account_name": "Checking", "account_type": "checking", "balance": 1000.0}]},
        ])
        mock_page.url = "https://bank.com/accounts"
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "john", "password": "secret"},
        )
        # Verify fill was called with real username, not placeholder
        mock_page.fill.assert_called_with("#user", "john")

    @pytest.mark.asyncio
    async def test_extract_action_returns_balances(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(return_value={
            "action": "extract",
            "balances": [
                {"account_name": "Checking", "account_type": "checking", "balance": 1500.0},
                {"account_name": "Visa", "account_type": "credit_card", "balance": 500.0, "available_credit": 4500.0},
            ],
        })
        result = await pilot.run(
            url="https://bank.com/accounts",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
        )
        assert result.status == "success"
        assert len(result.accounts) == 2
        assert result.accounts[0].balance == 1500.0

    @pytest.mark.asyncio
    async def test_mfa_action_returns_mfa_needed(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(return_value={
            "action": "mfa",
            "prompt": "Enter code sent to ***-1234",
        })
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
        )
        assert result.status == "mfa_needed"
        assert "1234" in result.mfa_prompt

    @pytest.mark.asyncio
    async def test_fail_action_returns_error(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(return_value={
            "action": "fail",
            "reason": "Invalid password",
        })
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
        )
        assert result.status == "login_failed"

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self, pilot, mock_page, mock_brain):
        # Always return click — should hit max steps
        mock_brain.query_json = AsyncMock(return_value={"action": "click", "selector": "#btn"})
        # Change URL each time so it doesn't trigger "nothing happened"
        call_count = 0
        async def changing_url():
            nonlocal call_count
            call_count += 1
            return f"<html><body><button id='btn'>Click {call_count}</button></body></html>"
        mock_page.content = changing_url
        mock_page.evaluate = AsyncMock(side_effect=lambda _: f"Page {call_count}")
        mock_page.url = property(lambda self: f"https://bank.com/page{call_count}")

        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "u", "password": "p"},
            max_steps=5,
        )
        assert result.status == "max_steps"

    @pytest.mark.asyncio
    async def test_credentials_never_in_actions_log(self, pilot, mock_page, mock_brain):
        mock_brain.query_json = AsyncMock(side_effect=[
            {"action": "fill", "selector": "#user", "value": "$cred.username"},
            {"action": "fill", "selector": "#pass", "value": "$cred.password"},
            {"action": "extract", "balances": [{"account_name": "Checking", "account_type": "checking", "balance": 100.0}]},
        ])
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Get balances",
            credentials={"username": "realuser", "password": "realpass"},
        )
        # Actions log should have placeholders, not real credentials
        actions_json = json.dumps(result.actions)
        assert "realuser" not in actions_json
        assert "realpass" not in actions_json
        assert "$cred.username" in actions_json
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/scrapers/test_pilot.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement pilot.py**

```python
# pa/scrapers/pilot.py
"""AI Pilot — Claude-driven browser navigation for any website."""

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pa.core.tier import Tier
from pa.scrapers.page_analyzer import clean_html, compute_page_hash, extract_visible_text, take_screenshot

logger = logging.getLogger(__name__)

_CRED_MAP = {"$cred.username": "username", "$cred.password": "password"}

PILOT_SYSTEM_PROMPT = """You are a browser navigation assistant. You are looking at a web page and deciding what action to take next.

Goal: {goal}

You have these credentials available:
- $cred.username
- $cred.password

Actions taken so far:
{action_history}

Current page URL: {url}
Current page HTML:
{cleaned_html}

Respond with ONLY a JSON object (no other text). Available actions:
- {{"action": "fill", "selector": "css-selector", "value": "text or $cred.username or $cred.password"}}
- {{"action": "click", "selector": "css-selector"}}
- {{"action": "screenshot", "reason": "why you need to see the page visually"}}
- {{"action": "wait", "wait_for": "selector|url", "value": "css-selector or url-pattern", "timeout_ms": 5000}}
- {{"action": "extract", "balances": [{{"account_name": "...", "account_type": "checking|savings|credit_card|mortgage|loan", "balance": 1234.56, "available_credit": null, "minimum_payment": null, "due_date": null, "statement_balance": null}}]}}
- {{"action": "mfa", "prompt": "the MFA prompt shown to the user"}}
- {{"action": "fail", "reason": "why this cannot proceed"}}

Rules:
- Use the most specific CSS selector you can find
- For credential fields, use $cred.username or $cred.password as the value
- If the HTML is unclear or you cannot determine what to do, request a screenshot
- If you see account balances on the page, extract them immediately
- If you see an MFA/verification code prompt, report it with the mfa action
- If login has clearly failed (wrong password message, locked account), use the fail action"""


@dataclass
class ScrapedAccount:
    account_name: str
    account_type: str
    balance: float
    available_credit: float | None = None
    minimum_payment: float | None = None
    due_date: str | None = None
    statement_balance: float | None = None


@dataclass
class PilotResult:
    status: Literal["success", "mfa_needed", "login_failed", "max_steps", "error"]
    accounts: list[ScrapedAccount] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    cookies: list[dict] = field(default_factory=list)
    mfa_prompt: str | None = None
    error: str | None = None


class AIPilot:
    """Navigates any website using Claude to analyze pages and decide actions."""

    def __init__(self, page: Any, brain: Any):
        self._page = page
        self._brain = brain
        self._screenshot_count = 0
        self._max_screenshots = 3

    async def run(
        self,
        url: str,
        goal: str,
        credentials: dict[str, str],
        resume_from: list[dict] | None = None,
        max_steps: int = 20,
        session_timeout: float = 300.0,  # 5 minutes overall
    ) -> PilotResult:
        actions: list[dict[str, Any]] = list(resume_from or [])
        session_start = time.monotonic()

        try:
            if not resume_from:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            return PilotResult(status="error", error=f"Failed to load {url}: {e}")

        prev_hash = ""

        for step in range(max_steps):
            # Check overall session timeout
            if time.monotonic() - session_start > session_timeout:
                return PilotResult(status="error", actions=actions, error=f"Session timeout ({session_timeout}s)")

            # Get page state
            try:
                html = await self._page.content()
                cleaned = clean_html(html)
                visible_text = await extract_visible_text(self._page)
                current_url = self._page.url
            except Exception as e:
                return PilotResult(status="error", actions=actions, error=f"Page read failed: {e}")

            # Check if page changed
            current_hash = compute_page_hash(current_url, visible_text)
            page_changed = current_hash != prev_hash
            prev_hash = current_hash

            # Build prompt
            action_history = json.dumps(actions[-10:], indent=2) if actions else "None yet"
            prompt = PILOT_SYSTEM_PROMPT.format(
                goal=goal,
                action_history=action_history,
                url=current_url,
                cleaned_html=cleaned,
            )

            if not page_changed and actions:
                prompt += "\n\nWARNING: The page did not change after your last action. Try a different approach."

            # Ask Claude
            try:
                action = await self._brain.query_json(
                    user_message="What is the next action?",
                    system_prompt=prompt,
                    tier=Tier.STANDARD,
                )
            except Exception as e:
                return PilotResult(status="error", actions=actions, error=f"Claude API error: {e}")

            action_type = action.get("action")
            logger.info("Pilot step %d: %s", step + 1, action_type)

            # Record action (with placeholders, not real creds)
            actions.append(action)

            # Execute action
            result = await self._execute_action(action, credentials, current_url, visible_text)
            if result is not None:
                result.actions = actions
                return result

            # Human-like delay
            await asyncio.sleep(random.uniform(0.5, 2.0))

        return PilotResult(status="max_steps", actions=actions, error=f"Exceeded {max_steps} navigation steps")

    async def _execute_action(
        self,
        action: dict[str, Any],
        credentials: dict[str, str],
        current_url: str,
        visible_text: str,
    ) -> PilotResult | None:
        """Execute a single action. Returns PilotResult if terminal, None to continue."""
        action_type = action.get("action")

        try:
            if action_type == "fill":
                value = self._resolve_credential(action.get("value", ""), credentials)
                await self._page.fill(action["selector"], value)
                # Add checkpoint hash to action record
                action["checkpoint"] = compute_page_hash(current_url, visible_text)
                return None

            elif action_type == "click":
                await self._page.click(action["selector"], timeout=15000)
                await self._page.wait_for_load_state("domcontentloaded", timeout=30000)
                action["checkpoint"] = compute_page_hash(current_url, visible_text)
                return None

            elif action_type == "screenshot":
                if self._screenshot_count >= self._max_screenshots:
                    logger.warning("Screenshot limit reached, continuing without")
                    return None
                self._screenshot_count += 1
                image = await take_screenshot(self._page)
                # Re-ask Claude with the screenshot — return None to continue loop
                # The next iteration will get Claude's vision-informed response
                try:
                    visual_action = await self._brain.query_json(
                        user_message="Here is a screenshot of the page. What action should I take?",
                        system_prompt=PILOT_SYSTEM_PROMPT.format(
                            goal="(see prior context)",
                            action_history="(see prior context)",
                            url=self._page.url,
                            cleaned_html="(screenshot provided instead)",
                        ),
                        tier=Tier.STANDARD,
                        image=image,
                    )
                    # Store the visual action in the caller's action list (not recursive)
                    self._last_visual_action = visual_action
                    return await self._execute_action(visual_action, credentials, current_url, visible_text)
                except Exception as e:
                    logger.warning("Vision call failed: %s", e)
                    return None

            elif action_type == "wait":
                wait_for = action.get("wait_for", "selector")
                value = action.get("value", "")
                timeout = action.get("timeout_ms", 5000)
                if wait_for == "url":
                    await self._page.wait_for_url(f"**{value}**", timeout=timeout)
                else:
                    await self._page.wait_for_selector(value, timeout=timeout)
                return None

            elif action_type == "extract":
                accounts = []
                for b in action.get("balances", []):
                    accounts.append(ScrapedAccount(
                        account_name=b.get("account_name", "Unknown"),
                        account_type=b.get("account_type", "checking"),
                        balance=float(b.get("balance", 0)),
                        available_credit=b.get("available_credit"),
                        minimum_payment=b.get("minimum_payment"),
                        due_date=b.get("due_date"),
                        statement_balance=b.get("statement_balance"),
                    ))
                return PilotResult(status="success", accounts=accounts)

            elif action_type == "mfa":
                return PilotResult(
                    status="mfa_needed",
                    mfa_prompt=action.get("prompt", "MFA code required"),
                )

            elif action_type == "fail":
                return PilotResult(
                    status="login_failed",
                    error=action.get("reason", "Unknown failure"),
                )

            else:
                logger.warning("Unknown action type: %s", action_type)
                return None

        except Exception as e:
            logger.warning("Action %s failed: %s", action_type, e)
            return None

    @staticmethod
    def _resolve_credential(value: str, credentials: dict[str, str]) -> str:
        """Replace $cred.* placeholders with real values."""
        if value in _CRED_MAP:
            return credentials.get(_CRED_MAP[value], value)
        return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/scrapers/test_pilot.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add pa/scrapers/pilot.py tests/scrapers/test_pilot.py
git commit -m "feat: add AI Pilot for Claude-driven browser navigation"
```

---

### Task 6: Update /addcred to Collect URL and Fix /creds Namespace

**Files:**
- Modify: `pa/core/bot.py`
- Modify: `tests/core/test_bot.py`

- [ ] **Step 1: Write test for the new addcred URL flow**

Add to `tests/core/test_bot.py`:

```python
class TestAddCredWithUrl:
    @pytest.mark.asyncio
    async def test_addcred_prompts_for_url(self, bot_instance, mock_update, mock_context):
        """After institution, next prompt should be for URL."""
        mock_context.args = ["wellsfargo"]
        await bot_instance._handle_addcred(mock_update, mock_context)
        reply_text = mock_update.message.reply_text.call_args[0][0]
        assert "URL" in reply_text or "url" in reply_text.lower()
        assert mock_context.user_data["addcred"]["step"] == "url"
```

Note: adapt fixture names to match existing test patterns in `tests/core/test_bot.py`.

- [ ] **Step 2: Update the addcred flow in bot.py**

The current flow is: institution → username → password.
The new flow is: institution → URL → username → password.

In `pa/core/bot.py`, modify `_handle_addcred` (line 155):

Change the handler so when institution is set, the next step is `"url"` instead of `"username"`:

```python
    async def _handle_addcred(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        institution = " ".join(context.args) if context.args else None
        if institution:
            context.user_data["addcred"] = {"institution": institution, "step": "url"}
            prompt = await update.message.reply_text(f"Login page URL for {institution}:")
            context.user_data["_addcred_prompt"] = prompt
        else:
            context.user_data["addcred"] = {"step": "institution"}
            prompt = await update.message.reply_text("Institution name (e.g. wellsfargo, synchrony):")
            context.user_data["_addcred_prompt"] = prompt
```

Then modify the text handler conversation flow (~line 237) to add the `url` step:

```python
            if step == "institution":
                addcred["institution"] = text
                addcred["step"] = "url"
                await self._delete_msg(update.message)
                prompt = await update.effective_chat.send_message(f"Login page URL for {text}:")
                context.user_data["_addcred_prompt"] = prompt
            elif step == "url":
                addcred["url"] = text
                addcred["step"] = "username"
                await self._delete_msg(update.message)
                prompt = await update.effective_chat.send_message(f"Username for {addcred['institution']}:")
                context.user_data["_addcred_prompt"] = prompt
            elif step == "username":
                # ... existing code unchanged
            elif step == "password":
                await self._delete_msg(update.message)
                institution = addcred["institution"]
                username = addcred["username"]
                url = addcred.get("url", "")
                del context.user_data["addcred"]
                try:
                    await self._vault.add(institution, {
                        "url": url,
                        "username": username,
                        "password": text,
                    })
                    await update.effective_chat.send_message(
                        f"Credentials saved for {institution}."
                    )
                except Exception as e:
                    await update.effective_chat.send_message(f"Error saving: {e}")
```

- [ ] **Step 3: Fix /creds to filter internal keys**

In `_handle_creds`, change the line that reads vault data to filter out internal keys:

```python
        creds = {k: v for k, v in self._vault._data.items() if not k.startswith("_")}
```

- [ ] **Step 4: Run bot tests**

Run: `python -m pytest tests/core/test_bot.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add pa/core/bot.py tests/core/test_bot.py
git commit -m "feat: add URL field to /addcred and filter internal vault keys from /creds"
```

---

### Task 7: Scraper Runner — Replace Hardcoded Logic with Pilot

**IMPORTANT:** Tasks 7 and 8 must be committed together or in immediate sequence — between them the system is broken (runner expects stdin, old commands.py passes argv). Implement both before running the bot.

**Files:**
- Rewrite: `pa/plugins/finance/scraper_runner.py`
- Create: `tests/plugins/finance/test_scraper_runner.py`

- [ ] **Step 1: Write failing test for the new runner protocol**

```python
# tests/plugins/finance/test_scraper_runner.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pa.plugins.finance.scraper_runner import run_scrape


class TestRunScrape:
    @pytest.mark.asyncio
    async def test_returns_success_result(self):
        mock_pilot_result = MagicMock()
        mock_pilot_result.status = "success"
        mock_pilot_result.accounts = [
            MagicMock(account_name="Checking", account_type="checking", balance=1500.0,
                      available_credit=None, minimum_payment=None, due_date=None, statement_balance=None)
        ]
        mock_pilot_result.actions = [{"action": "click", "selector": "#btn"}]
        mock_pilot_result.cookies = [{"name": "s", "value": "v"}]
        mock_pilot_result.mfa_prompt = None
        mock_pilot_result.error = None

        with patch("pa.plugins.finance.scraper_runner._create_pilot") as mock_create:
            mock_pilot = AsyncMock()
            mock_pilot.run = AsyncMock(return_value=mock_pilot_result)
            mock_create.return_value = (mock_pilot, AsyncMock())  # (pilot, cleanup)

            result = await run_scrape(
                url="https://bank.com/login",
                credentials={"username": "u", "password": "p"},
                data_dir="/tmp",
            )
        assert result["status"] == "success"
        assert len(result["accounts"]) == 1
        assert result["accounts"][0]["account_name"] == "Checking"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/plugins/finance/test_scraper_runner.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite scraper_runner.py**

```python
# pa/plugins/finance/scraper_runner.py
"""Subprocess scraper runner using AI Pilot.

Protocol: reads credentials from stdin, writes JSON events to stdout.
Events: {"event": "progress", "message": "..."}
        {"event": "mfa_needed", "prompt": "..."}
        {"event": "complete", "result": {...}}

MFA: reads {"event": "mfa_code", "code": "..."} from stdin when MFA is needed.
"""

import asyncio
import json
import logging
import os
import random
import sys
from typing import Any

from pa.core.tier import Tier

logger = logging.getLogger(__name__)


def _emit(event: dict) -> None:
    """Write a JSON event to stdout."""
    print(json.dumps(event), flush=True)


async def _create_pilot(data_dir: str) -> tuple:
    """Create an AIPilot with a Playwright browser. Returns (pilot, cleanup_fn)."""
    from playwright.async_api import async_playwright
    from pa.core.brain import Brain
    from pa.scrapers.pilot import AIPilot

    pw = await async_playwright().start()

    launch_args = [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--js-flags=--max-old-space-size=256",
    ]

    browser = await pw.chromium.launch(headless=True, args=launch_args)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    # Block heavy resources
    await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot}", lambda route: route.abort())
    await context.route("**/*google*analytics*", lambda route: route.abort())
    await context.route("**/*doubleclick*", lambda route: route.abort())

    page = await context.new_page()

    # Lightweight brain config for subprocess
    brain_config = {"claude_api_key_env": "PA_CLAUDE_API_KEY", "cost_cap_monthly_usd": 20.0}
    brain = Brain(brain_config)

    pilot = AIPilot(page, brain)

    async def cleanup():
        await browser.close()
        await pw.stop()

    return pilot, cleanup


async def run_scrape(
    url: str,
    credentials: dict[str, str],
    data_dir: str,
    cookies: list[dict] | None = None,
    recipe: list[dict] | None = None,
) -> dict[str, Any]:
    """Run the AI Pilot to scrape an institution. Returns result dict.

    Cascade: cookies (session reuse) → recipe (replay) → AI Pilot (from scratch).
    """
    pilot, cleanup = await _create_pilot(data_dir)
    try:
        page = pilot._page

        # Phase 1: Try session reuse with saved cookies
        if cookies:
            _emit({"event": "progress", "message": "Trying saved session..."})
            context = page.context
            await context.add_cookies(cookies)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Check if we landed on an accounts page (not redirected to login)
            # Use a quick Claude check
            from pa.scrapers.page_analyzer import get_cleaned_html
            html = await get_cleaned_html(page)
            try:
                check = await pilot._brain.query_json(
                    user_message="Does this page show account balances or a dashboard (not a login form)? Respond with {\"logged_in\": true/false}.",
                    system_prompt="You are checking if a browser session is still valid. Look at the HTML and determine if this is a logged-in dashboard/accounts page or a login page.",
                    tier=Tier.FAST,
                )
                if check.get("logged_in"):
                    _emit({"event": "progress", "message": "Session valid! Extracting balances..."})
                    # Ask pilot to extract balances from this page
                    result = await pilot.run(
                        url=page.url,
                        goal="Extract all account balances from this page. You are already logged in.",
                        credentials=credentials,
                        max_steps=5,
                    )
                    if result.status == "success":
                        return _format_result(result)
            except Exception:
                pass  # Session check failed, continue to recipe/pilot

        # Phase 2: Try recipe replay
        if recipe:
            _emit({"event": "progress", "message": "Replaying saved recipe..."})
            from pa.scrapers.recipe import RecipeEngine
            resolved = RecipeEngine.resolve_credentials(recipe, credentials)
            replay_ok = True
            replay_step = 0
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            for i, step in enumerate(resolved):
                try:
                    action = step.get("action")
                    if action == "fill":
                        await page.fill(step["selector"], step["value"], timeout=10000)
                    elif action == "click":
                        await page.click(step["selector"], timeout=10000)
                        await page.wait_for_load_state("domcontentloaded", timeout=30000)
                    elif action == "wait":
                        wait_for = step.get("wait_for", "selector")
                        if wait_for == "url":
                            await page.wait_for_url(step["value"], timeout=step.get("timeout_ms", 5000))
                        else:
                            await page.wait_for_selector(step["value"], timeout=step.get("timeout_ms", 5000))
                    elif action == "extract":
                        # Recipe reached extraction — run pilot to re-extract from current page
                        result = await pilot.run(
                            url=page.url,
                            goal="Extract all account balances from this page. You are already logged in.",
                            credentials=credentials,
                            max_steps=5,
                        )
                        return _format_result(result)
                    import asyncio as _asyncio
                    await _asyncio.sleep(random.uniform(0.3, 1.0))
                except Exception as e:
                    logger.info("Recipe replay failed at step %d: %s", i, e)
                    replay_ok = False
                    replay_step = i
                    break

            if replay_ok:
                # Recipe completed but no extract step — try pilot extraction
                result = await pilot.run(
                    url=page.url,
                    goal="Extract all account balances from this page.",
                    credentials=credentials,
                    max_steps=5,
                )
                return _format_result(result)
            else:
                _emit({"event": "progress", "message": f"Recipe failed at step {replay_step}, switching to AI..."})

        # Phase 3: AI Pilot from scratch
        _emit({"event": "progress", "message": "AI navigating site..."})
        result = await pilot.run(
            url=url,
            goal="Log in using the provided credentials and find all account balances. Extract every account with its name, type, and balance.",
            credentials=credentials,
        )
        return _format_result(result)

    finally:
        await cleanup()


async def run_scrape_resume_mfa(
    url: str,
    credentials: dict[str, str],
    data_dir: str,
    mfa_code: str,
    prior_actions: list[dict],
) -> dict[str, Any]:
    """Resume a scrape after MFA code is provided."""
    pilot, cleanup = await _create_pilot(data_dir)
    try:
        # Replay prior actions to get back to MFA page
        page = pilot._page
        from pa.scrapers.recipe import RecipeEngine
        resolved = RecipeEngine.resolve_credentials(prior_actions, credentials)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for step in resolved:
            action = step.get("action")
            try:
                if action == "fill":
                    await page.fill(step["selector"], step["value"], timeout=10000)
                elif action == "click":
                    await page.click(step["selector"], timeout=10000)
                    await page.wait_for_load_state("domcontentloaded", timeout=30000)
                elif action in ("mfa", "extract", "fail", "screenshot"):
                    break  # Stop at MFA/terminal action
            except Exception:
                break
            import asyncio as _asyncio
            await _asyncio.sleep(random.uniform(0.3, 1.0))

        # Now enter the MFA code and continue with pilot
        result = await pilot.run(
            url=page.url,
            goal=f"Enter the MFA verification code '{mfa_code}' and then find all account balances.",
            credentials=credentials,
            max_steps=15,
        )
        return _format_result(result)
    finally:
        await cleanup()


def _format_result(result) -> dict[str, Any]:
    """Convert PilotResult to serializable dict."""
    accounts = [
        {
            "account_name": a.account_name,
            "account_type": a.account_type,
            "balance": a.balance,
            "available_credit": a.available_credit,
            "minimum_payment": a.minimum_payment,
            "due_date": a.due_date,
            "statement_balance": a.statement_balance,
        }
        for a in result.accounts
    ]
    return {
        "status": result.status,
        "accounts": accounts,
        "actions": result.actions,
        "cookies": result.cookies,
        "mfa_prompt": result.mfa_prompt,
        "error": result.error,
    }


async def _main() -> None:
    """Subprocess entry point. Reads config from stdin, runs scrape, writes results to stdout."""
    # Read credentials from stdin
    input_line = sys.stdin.readline().strip()
    config = json.loads(input_line)

    url = config["url"]
    credentials = config["credentials"]
    data_dir = config.get("data_dir", ".")
    saved_cookies = config.get("cookies")  # Pre-loaded cookies for session reuse
    saved_recipe = config.get("recipe")    # Pre-loaded recipe for replay

    _emit({"event": "progress", "message": f"Starting scrape of {url}"})

    try:
        result = await run_scrape(url, credentials, data_dir,
                                   cookies=saved_cookies, recipe=saved_recipe)

        if result["status"] == "mfa_needed":
            _emit({"event": "mfa_needed", "prompt": result["mfa_prompt"]})
            # Block waiting for MFA code from stdin (bot relays user's reply)
            mfa_line = sys.stdin.readline().strip()
            if not mfa_line:
                _emit({"event": "complete", "result": {"status": "error", "error": "MFA timeout — no code received", "accounts": []}})
                return
            mfa_msg = json.loads(mfa_line)
            if mfa_msg.get("event") == "mfa_code":
                code = mfa_msg["code"]
                _emit({"event": "progress", "message": "MFA code received, resuming..."})
                # Resume the pilot with MFA code — the pilot needs to enter the code and continue
                result = await run_scrape_resume_mfa(url, credentials, data_dir, code, result.get("actions", []))

        _emit({"event": "complete", "result": result})

    except Exception as e:
        _emit({"event": "complete", "result": {"status": "error", "error": str(e), "accounts": []}})


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/plugins/finance/test_scraper_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pa/plugins/finance/scraper_runner.py tests/plugins/finance/test_scraper_runner.py
git commit -m "feat: rewrite scraper runner to use AI Pilot instead of hardcoded logic"
```

---

### Task 8: Update /scrape Command — Full Cascade with MFA Relay and Login Cooldown

**Files:**
- Modify: `pa/plugins/finance/commands.py`
- Create: `tests/plugins/finance/test_scrape_command.py`

- [ ] **Step 1: Write tests for the new scrape command**

```python
# tests/plugins/finance/test_scrape_command.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pa.plugins.finance.commands import handle_scrape, _scrape_lock, _login_failures


@pytest.fixture
def mock_ctx():
    ctx = MagicMock()
    ctx.vault.is_unlocked = True
    ctx.vault.get.return_value = {"url": "https://bank.com/login", "username": "u", "password": "p"}
    ctx.vault._data = {"bank": {"url": "https://bank.com/login", "username": "u", "password": "p"}}
    ctx.config.get.return_value = "."
    ctx.store = MagicMock()
    return ctx


@pytest.fixture
def mock_update():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def mock_context_args():
    ctx = MagicMock()
    ctx.args = ["bank"]
    return ctx


class TestHandleScrape:
    @pytest.mark.asyncio
    async def test_rejects_missing_institution(self, mock_ctx, mock_update):
        ctx = MagicMock()
        ctx.args = []
        result = await handle_scrape(mock_ctx, mock_update, ctx)
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_rejects_locked_vault(self, mock_ctx, mock_update, mock_context_args):
        mock_ctx.vault.is_unlocked = False
        result = await handle_scrape(mock_ctx, mock_update, mock_context_args)
        assert "locked" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_url(self, mock_ctx, mock_update, mock_context_args):
        mock_ctx.vault.get.return_value = {"username": "u", "password": "p"}  # no URL
        result = await handle_scrape(mock_ctx, mock_update, mock_context_args)
        assert "URL" in result

    @pytest.mark.asyncio
    async def test_rejects_when_cooldown_active(self, mock_ctx, mock_update, mock_context_args):
        import time
        _login_failures["bank"] = {"count": 2, "blocked_until": time.time() + 3600}
        try:
            result = await handle_scrape(mock_ctx, mock_update, mock_context_args)
            assert "blocked" in result.lower() or "cooldown" in result.lower()
        finally:
            _login_failures.pop("bank", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/plugins/finance/test_scrape_command.py -v`
Expected: FAIL (functions don't exist yet in new form)

- [ ] **Step 3: Rewrite handle_scrape in commands.py**

Replace the current `handle_scrape` function with the full cascade: cookies → recipe → pilot, with MFA relay and login cooldown.

```python
import asyncio
import json
import sys
import time
from typing import Any

from pa.plugins import AppContext
from pa.plugins.finance.repository import FinanceRepository

_scrape_lock = asyncio.Lock()
_login_failures: dict[str, dict] = {}  # {institution: {"count": int, "blocked_until": float}}
_COOLDOWN_SECONDS = 3600  # 1 hour cooldown after 2 failures
_MAX_FAILURES_BEFORE_COOLDOWN = 2


def _repo(ctx: AppContext) -> FinanceRepository:
    return FinanceRepository(ctx.store)


def _check_cooldown(institution: str) -> str | None:
    """Check if institution is in login failure cooldown. Returns error message or None."""
    info = _login_failures.get(institution)
    if info and info["count"] >= _MAX_FAILURES_BEFORE_COOLDOWN:
        if time.time() < info["blocked_until"]:
            remaining = int(info["blocked_until"] - time.time()) // 60
            return f"Scraping {institution} is blocked for ~{remaining} min after repeated login failures. Check your credentials with /creds."
        else:
            # Cooldown expired, reset
            _login_failures.pop(institution, None)
    return None


def _record_login_failure(institution: str) -> None:
    """Record a login failure. After 2, block for 1 hour."""
    info = _login_failures.get(institution, {"count": 0, "blocked_until": 0})
    info["count"] = info.get("count", 0) + 1
    if info["count"] >= _MAX_FAILURES_BEFORE_COOLDOWN:
        info["blocked_until"] = time.time() + _COOLDOWN_SECONDS
    _login_failures[institution] = info


async def handle_scrape(ctx: AppContext, update: Any, context: Any) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    institution = context.args[0] if context.args else None
    if not institution:
        return "Usage: /scrape <institution>"

    creds = ctx.vault.get(institution)
    if not creds:
        return f"No credentials for '{institution}'. Use /addcred first."

    url = creds.get("url")
    if not url:
        return f"No login URL stored for '{institution}'. Use /addcred to re-add with URL."

    # Check login failure cooldown
    cooldown_msg = _check_cooldown(institution)
    if cooldown_msg:
        return cooldown_msg

    if _scrape_lock.locked():
        return "A scrape is already in progress. Please wait."

    async with _scrape_lock:
        repo = _repo(ctx)
        start_time = time.time()

        await update.message.reply_text(f"Scraping {institution}...")

        try:
            # Launch subprocess
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pa.plugins.finance.scraper_runner",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Send config via stdin (credentials never on command line)
            # Include saved cookies for session reuse
            from pa.scrapers.session_store import SessionStore
            session_store = SessionStore(ctx.vault)
            saved_cookies = await session_store.load_cookies(institution)

            # Include saved recipe for replay
            from pa.scrapers.recipe import RecipeEngine
            recipe_engine = RecipeEngine(ctx.store)
            recipe = await recipe_engine.get_recipe(f"scrape_{institution}")
            saved_recipe = json.loads(recipe["steps"]) if recipe else None

            config = json.dumps({
                "url": url,
                "credentials": {"username": creds["username"], "password": creds["password"]},
                "data_dir": str(ctx.config.get("data_dir", ".")),
                "cookies": saved_cookies,
                "recipe": saved_recipe,
            })
            proc.stdin.write(config.encode() + b"\n")
            await proc.stdin.drain()

            result = None
            # Read events from stdout
            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=300)
                except asyncio.TimeoutError:
                    proc.kill()
                    await repo.log_scrape(institution, "failure", error_message="Timeout after 300s", duration_seconds=time.time() - start_time)
                    return f"Scrape of {institution} timed out after 5 minutes."

                if not line:
                    break

                try:
                    event = json.loads(line.decode().strip())
                except json.JSONDecodeError:
                    continue

                if event.get("event") == "progress":
                    pass  # Could forward status to user

                elif event.get("event") == "mfa_needed":
                    # MFA relay: ask user for code via Telegram, send to subprocess
                    prompt = event.get("prompt", "MFA code required")
                    await update.message.reply_text(f"MFA required: {prompt}\nReply with your code within 5 minutes.")

                    # Store subprocess reference so MFA handler can write to it
                    # The bot's text handler checks for _mfa_pending and relays the code
                    ctx.bot._mfa_subprocess = proc
                    ctx.bot._mfa_institution = institution

                    # Wait for code to be relayed (subprocess blocks on stdin.readline)
                    # The bot text handler will write to proc.stdin when user replies
                    # We just continue reading stdout for the next event
                    continue

                elif event.get("event") == "complete":
                    result = event.get("result", {})
                    break

            # Clean up MFA state
            if hasattr(ctx.bot, '_mfa_subprocess'):
                del ctx.bot._mfa_subprocess
                del ctx.bot._mfa_institution

            await proc.wait()
            duration = time.time() - start_time

            if result is None:
                await repo.log_scrape(institution, "failure", error_message="No result from subprocess", duration_seconds=duration)
                return f"Scrape of {institution} failed — no result received."

            # Handle login failure cooldown
            if result.get("status") == "login_failed":
                _record_login_failure(institution)
                error = result.get("error", "Unknown error")
                await repo.log_scrape(institution, "failure", error_message=error, duration_seconds=duration)
                failures = _login_failures.get(institution, {}).get("count", 0)
                if failures >= _MAX_FAILURES_BEFORE_COOLDOWN:
                    return f"Scrape of {institution} failed: {error}\nBlocked for 1 hour after {failures} consecutive failures."
                return f"Scrape of {institution} failed: {error}"

            if result.get("status") != "success":
                error = result.get("error", "Unknown error")
                await repo.log_scrape(institution, "failure", error_message=error, duration_seconds=duration)
                return f"Scrape of {institution} failed: {error}"

            # Success — clear any login failure tracking
            _login_failures.pop(institution, None)

            # Store balances
            accounts = result.get("accounts", [])
            if not accounts:
                await repo.log_scrape(institution, "failure", error_message="No accounts found", duration_seconds=duration)
                return f"Scrape of {institution} succeeded but found no accounts."

            existing = await repo.get_accounts()
            existing_map = {(a["institution"], a["name"]): a["id"] for a in existing}

            stored_count = 0
            for acct in accounts:
                key = (institution, acct["account_name"])
                if key in existing_map:
                    account_id = existing_map[key]
                else:
                    account_id = await repo.add_account(
                        institution=institution,
                        name=acct["account_name"],
                        account_type=acct.get("account_type", "checking"),
                    )

                await repo.add_balance(
                    account_id=account_id,
                    balance=acct["balance"],
                    statement_balance=acct.get("statement_balance"),
                    available_credit=acct.get("available_credit"),
                    minimum_payment=acct.get("minimum_payment"),
                    due_date=acct.get("due_date"),
                )
                stored_count += 1

            # Store cookies for session persistence
            cookies = result.get("cookies", [])
            if cookies:
                await session_store.save_cookies(institution, cookies)

            # Store recipe for future replay
            actions = result.get("actions", [])
            if actions:
                await recipe_engine.record(f"scrape_{institution}", "finance", actions)

            await repo.log_scrape(institution, "success", duration_seconds=duration)

            lines = [f"Scraped {institution} ({duration:.1f}s) — {stored_count} accounts:"]
            for acct in accounts:
                balance_str = f"${acct['balance']:,.2f}"
                lines.append(f"  {acct['account_name']}: {balance_str}")
            return "\n".join(lines)

        except Exception as e:
            duration = time.time() - start_time
            await repo.log_scrape(institution, "failure", error_message=str(e), duration_seconds=duration)
            return f"Scrape of {institution} failed: {e}"
```

- [ ] **Step 4: Remove old handle_scrape and hardcoded logic**

Remove:
- The old `handle_scrape` function entirely
- Any `{"wellsfargo"}` hardcoded institution checks
- The old `SCRAPE_RESULT:` parsing logic
- The Claude HTML fallback parsing

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/plugins/finance/test_scrape_command.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add pa/plugins/finance/commands.py tests/plugins/finance/test_scrape_command.py
git commit -m "feat: rewrite /scrape with cookie/recipe cascade, MFA relay, and login cooldown"
```

---

### Task 8b: MFA Relay in Bot Text Handler

**Files:**
- Modify: `pa/core/bot.py`

- [ ] **Step 1: Add MFA subprocess relay to the text handler**

In `pa/core/bot.py`, in the `_handle_text` method, add a check before the existing MFA bridge handling (~line 274):

```python
        # MFA relay to scraper subprocess
        if hasattr(self, '_mfa_subprocess') and self._mfa_subprocess:
            proc = self._mfa_subprocess
            code = update.message.text.strip()
            try:
                mfa_msg = json.dumps({"event": "mfa_code", "code": code})
                proc.stdin.write(mfa_msg.encode() + b"\n")
                await proc.stdin.drain()
                await update.message.reply_text(f"MFA code sent. Continuing scrape...")
            except Exception as e:
                await update.message.reply_text(f"Failed to relay MFA code: {e}")
            finally:
                self._mfa_subprocess = None
                self._mfa_institution = None
            return
```

Add `import json` at the top of `bot.py` if not already present.

- [ ] **Step 2: Run bot tests**

Run: `python -m pytest tests/core/test_bot.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add pa/core/bot.py
git commit -m "feat: add MFA code relay from Telegram to scraper subprocess"
```

---

### Task 9: Delete Hardcoded Scrapers and Cleanup

**Files:**
- Delete: `pa/plugins/finance/scrapers/wellsfargo.py`
- Delete: `pa/plugins/finance/scrapers/synchrony.py`
- Delete: `pa/plugins/finance/scrapers/credit_one.py`
- Delete: `tools/probe_wf.py`
- Modify: `pa/plugins/finance/scrapers/__init__.py` (if it exports anything)

- [ ] **Step 1: Check what's in the scrapers __init__.py**

Read `pa/plugins/finance/scrapers/__init__.py` to see if there are exports that need updating.

- [ ] **Step 2: Delete hardcoded scrapers**

```bash
rm pa/plugins/finance/scrapers/wellsfargo.py
rm pa/plugins/finance/scrapers/synchrony.py
rm pa/plugins/finance/scrapers/credit_one.py
rm tools/probe_wf.py
```

- [ ] **Step 3: Update scrapers __init__.py**

Remove any imports of deleted scrapers. If it's empty, leave it as an empty `__init__.py` or remove the directory if nothing else references it.

- [ ] **Step 4: Run all tests to check for broken imports**

Run: `python -m pytest -v`
Expected: All PASS. If any test imports deleted scrapers, remove those tests too.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove hardcoded bank scrapers replaced by AI Pilot"
```

---

### Task 10: Integration Test — Full Pilot Flow with Mock Pages

**Files:**
- Create: `tests/scrapers/test_pilot_integration.py`

- [ ] **Step 1: Write integration test with a mock login page**

```python
# tests/scrapers/test_pilot_integration.py
"""Integration test: Pilot navigates a local HTML login page."""
import json
import pytest
from unittest.mock import AsyncMock
from pa.scrapers.pilot import AIPilot, ScrapedAccount


@pytest.fixture
def mock_brain_sequence():
    """Brain that returns a realistic login sequence."""
    brain = AsyncMock()
    brain.query_json = AsyncMock(side_effect=[
        # Step 1: Fill username
        {"action": "fill", "selector": "#username", "value": "$cred.username"},
        # Step 2: Fill password
        {"action": "fill", "selector": "#password", "value": "$cred.password"},
        # Step 3: Click login
        {"action": "click", "selector": "#login-btn"},
        # Step 4: Extract balances from accounts page
        {
            "action": "extract",
            "balances": [
                {"account_name": "Checking ****1234", "account_type": "checking", "balance": 2500.00},
                {"account_name": "Savings ****5678", "account_type": "savings", "balance": 10000.00},
            ],
        },
    ])
    return brain


@pytest.fixture
def mock_page_login_flow():
    """Page that simulates a login form → accounts page transition."""
    page = AsyncMock()
    pages = [
        # Login page HTML
        '<html><body><form><input id="username" type="text"/><input id="password" type="password"/><button id="login-btn">Sign In</button></form></body></html>',
        # Same during fill actions
        '<html><body><form><input id="username" type="text"/><input id="password" type="password"/><button id="login-btn">Sign In</button></form></body></html>',
        '<html><body><form><input id="username" type="text"/><input id="password" type="password"/><button id="login-btn">Sign In</button></form></body></html>',
        # Accounts page after login
        '<html><body><h1>Your Accounts</h1><div>Checking ****1234: $2,500.00</div><div>Savings ****5678: $10,000.00</div></body></html>',
    ]
    texts = ["Sign In", "Sign In", "Sign In", "Your Accounts Checking Savings"]
    urls = [
        "https://bank.com/login", "https://bank.com/login",
        "https://bank.com/login", "https://bank.com/accounts",
    ]
    call_idx = {"n": 0}

    async def get_content():
        idx = min(call_idx["n"], len(pages) - 1)
        call_idx["n"] += 1
        return pages[idx]

    async def get_text(_):
        idx = min(call_idx["n"] - 1, len(texts) - 1)
        return texts[max(0, idx)]

    page.content = get_content
    page.evaluate = get_text
    page.goto = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG")

    # URL changes after click
    type(page).url = property(lambda self: urls[min(call_idx["n"] - 1, len(urls) - 1)] if call_idx["n"] > 0 else urls[0])

    return page


class TestPilotIntegration:
    @pytest.mark.asyncio
    async def test_full_login_and_extract(self, mock_page_login_flow, mock_brain_sequence):
        pilot = AIPilot(mock_page_login_flow, mock_brain_sequence)
        result = await pilot.run(
            url="https://bank.com/login",
            goal="Log in and get balances",
            credentials={"username": "testuser", "password": "testpass"},
        )

        assert result.status == "success"
        assert len(result.accounts) == 2
        assert result.accounts[0].account_name == "Checking ****1234"
        assert result.accounts[0].balance == 2500.00
        assert result.accounts[1].account_type == "savings"

        # Verify credentials were filled correctly
        mock_page_login_flow.fill.assert_any_call("#username", "testuser")
        mock_page_login_flow.fill.assert_any_call("#password", "testpass")
        mock_page_login_flow.click.assert_called_with("#login-btn", timeout=15000)

        # Verify actions were recorded with placeholders
        actions_json = json.dumps(result.actions)
        assert "testuser" not in actions_json
        assert "$cred.username" in actions_json
        assert len(result.actions) == 4
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/scrapers/test_pilot_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/scrapers/test_pilot_integration.py
git commit -m "test: add Pilot integration test with mock login flow"
```

---

### Task 11: Final Cleanup and Full Test Run

- [ ] **Step 1: Remove the old scraper_runner.py __main__ imports from commands.py if any remain**

Check `pa/plugins/finance/commands.py` for any references to `wellsfargo`, `SCRAPE_RESULT`, or old parsing logic. Remove them.

- [ ] **Step 2: Check for any remaining imports of deleted scrapers**

Run: `python -m pytest -v` and fix any import errors.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest -v`
Expected: All tests PASS. No import errors, no broken references.

- [ ] **Step 4: Commit any remaining fixes**

```bash
git add -A
git commit -m "chore: final cleanup after AI Pilot migration"
```

---

## Summary

| Task | Component | Description |
|------|-----------|-------------|
| 1 | Page Analyzer | HTML cleaning, truncation, page hashing |
| 2 | Session Store | Encrypted cookie persistence in vault |
| 3 | Brain.query_json | Structured JSON responses with vision support |
| 4 | Recipe v2 | Checkpoint hashing, replay executor, schema bump |
| 5 | AI Pilot | Core navigation loop with session timeout (biggest task) |
| 6 | /addcred URL | Add URL field to credential flow, filter internal vault keys |
| 7 | Scraper Runner | Rewrite with Pilot, cookie/recipe cascade, MFA resume |
| 8 | /scrape Command | Full cascade: cookies → recipe → pilot, MFA relay, login cooldown |
| 8b | MFA Relay | Bot text handler relays MFA codes to subprocess |
| 9 | Delete Old Scrapers | Remove WF, Synchrony, CreditOne, probe |
| 10 | Integration Test | Full login flow test with mock pages |
| 11 | Final Cleanup | Remove stale references, full test pass |
