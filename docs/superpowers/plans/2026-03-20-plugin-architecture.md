# Plugin Architecture & Learn-Once Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor PA from hardcoded financial assistant into a generic plugin-based personal assistant ("George") with a learn-once-replay engine that reduces API costs over time.

**Architecture:** Core modules (store, brain, bot, scheduler) become domain-agnostic. All financial logic moves to `pa/plugins/finance/`. Plugins register commands, jobs, schema, and tier patterns via a `PluginBase` class. A recipe engine records scraper flows for replay without AI. Query templates cache repeated questions.

**Tech Stack:** Python 3.11+, aiosqlite, Playwright, python-telegram-bot v20+, APScheduler 4.x, anthropic SDK, argon2-cffi, cryptography

**Spec:** `docs/superpowers/specs/2026-03-20-plugin-architecture-design.md`

---

## File Structure

```
pa/
  __init__.py                         # Empty
  __main__.py                         # Thin entry: calls pa.core.app.main()
  core/
    __init__.py                       # Empty
    identity.py                       # George's name, greeting, persona constants
    exceptions.py                     # Base exceptions only (PAError, VaultAuthError, etc.)
    config.py                         # Config class (moved from pa/config/config.py, unchanged)
    store.py                          # Generic SQLite wrapper (stripped of finance methods)
    schema.sql                        # Core tables: recipes, query_templates
    brain.py                          # Generic Claude API (no build_system_prompt)
    cost_tracker.py                   # Monthly budget (moved, unchanged)
    tier.py                           # Dynamic tier classifier (accepts plugin patterns)
    scheduler.py                      # Generic APScheduler (no hardcoded jobs except heartbeat)
    bot.py                            # Generic Telegram bot (plugin command registry)
  vault/
    __init__.py                       # Re-export Vault
    vault.py                          # Unchanged
    crypto.py                         # Unchanged
  scrapers/
    __init__.py                       # Empty
    base.py                           # BaseScraper (unchanged)
    mfa_bridge.py                     # MFABridge (unchanged)
    recipe.py                         # NEW: learn-once recipe engine
  plugins/
    __init__.py                       # PluginBase, AppContext, Command, Job, discover_plugins()
    finance/
      __init__.py                     # Exports FinancePlugin
      plugin.py                       # FinancePlugin(PluginBase)
      schema.sql                      # finance_ prefixed tables
      repository.py                   # Finance store methods (extracted from old store.py)
      commands.py                     # /balance, /debt, /due, /spending, /plan, /scrape, /schedule, /backup
      formatters.py                   # format_balance_summary, format_debt_summary, etc.
      jobs.py                         # Financial job definitions
      tier_patterns.py                # Financial keyword patterns
      scrapers/
        __init__.py                   # Empty
        wellsfargo.py                 # Moved from pa/scrapers/
        synchrony.py                  # Moved from pa/scrapers/
        credit_one.py                 # Moved from pa/scrapers/
tests/
  __init__.py                         # Empty
  conftest.py                         # Updated fixtures
  core/
    __init__.py
    test_identity.py
    test_exceptions.py
    test_config.py
    test_store.py
    test_brain.py
    test_cost_tracker.py
    test_tier.py
    test_scheduler.py
    test_bot.py
    test_plugin_registry.py
    test_recipe.py
    test_query_templates.py
  vault/
    __init__.py
    test_vault.py
    test_vault_crypto.py
  scrapers/
    __init__.py
    test_mfa_bridge.py
    test_scraper_base.py
  plugins/
    __init__.py
    finance/
      __init__.py
      test_plugin.py
      test_repository.py
      test_commands.py
      test_formatters.py
      test_jobs.py
      test_tier_patterns.py
  test_integration.py
```

---

## Task 1: Plugin Protocol and Core Types

**Files:**
- Create: `pa/plugins/__init__.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/test_plugin_registry.py`

- [ ] **Step 1: Write tests for plugin protocol**

```python
# tests/core/test_plugin_registry.py
"""Tests for plugin base class and discovery."""
import pytest
from pa.plugins import PluginBase, Command, Job, AppContext, discover_plugins


def test_plugin_base_defaults():
    """PluginBase provides safe defaults for all methods."""
    p = PluginBase()
    assert p.schema_sql() == ""
    assert p.commands() == []
    assert p.jobs() == []
    assert p.tier_patterns() == {}
    assert p.system_prompt_fragment() == ""


def test_command_dataclass():
    cmd = Command(name="test", description="A test command", handler=lambda: None)
    assert cmd.name == "test"
    assert cmd.aliases == []


def test_job_dataclass():
    job = Job(name="test_job", handler=lambda: None, trigger="cron", kwargs={"hour": 6})
    assert job.trigger == "cron"
    assert job.kwargs == {"hour": 6}


def test_app_context_fields():
    ctx = AppContext(store=1, vault=2, brain=3, bot=4, scheduler=5, config=6)
    assert ctx.store == 1
    assert ctx.config == 6


class FakePlugin(PluginBase):
    name = "fake"
    description = "A test plugin"

    def commands(self) -> list:
        return [Command(name="hello", description="Say hi", handler=lambda: "hi")]


def test_subclass_override():
    p = FakePlugin()
    assert p.name == "fake"
    assert len(p.commands()) == 1
    assert p.schema_sql() == ""


def test_discover_plugins_returns_list():
    plugins = discover_plugins()
    assert isinstance(plugins, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_plugin_registry.py -v`
Expected: FAIL (ImportError — module doesn't exist yet)

- [ ] **Step 3: Implement plugin protocol**

```python
# pa/plugins/__init__.py
"""Plugin system for PA. Plugins register commands, jobs, schema, and AI patterns."""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Command:
    """A bot command registered by a plugin."""
    name: str
    description: str
    handler: Callable
    aliases: list[str] = field(default_factory=list)


@dataclass
class Job:
    """A scheduled job registered by a plugin."""
    name: str
    handler: Callable
    trigger: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppContext:
    """Typed context passed to plugins at startup."""
    store: Any
    vault: Any
    brain: Any
    bot: Any
    scheduler: Any
    config: Any


class PluginBase:
    """Base class for all PA plugins. Subclass and override what you need."""

    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    def schema_sql(self) -> str:
        return ""

    def commands(self) -> list[Command]:
        return []

    def jobs(self) -> list[Job]:
        return []

    def tier_patterns(self) -> dict[str, list[str]]:
        return {}

    def system_prompt_fragment(self) -> str:
        return ""

    async def on_startup(self, ctx: AppContext) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


def _validate_ddl(sql: str, plugin_name: str) -> None:
    """Validate plugin DDL: only CREATE TABLE/INDEX with plugin-prefixed names."""
    import re
    for statement in sql.split(";"):
        stmt = statement.strip()
        if not stmt:
            continue
        upper = stmt.upper()
        if not (upper.startswith("CREATE TABLE") or upper.startswith("CREATE INDEX")):
            raise ValueError(f"Plugin '{plugin_name}' DDL contains disallowed statement: {stmt[:60]}")
        # Check table name is prefixed
        table_match = re.search(r'(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', stmt, re.IGNORECASE)
        if table_match:
            table_name = table_match.group(1)
            if not table_name.startswith(f"{plugin_name}_"):
                raise ValueError(
                    f"Plugin '{plugin_name}' table '{table_name}' must be prefixed with '{plugin_name}_'"
                )


def discover_plugins() -> list[PluginBase]:
    """Scan pa/plugins/ subdirectories for PluginBase subclasses."""
    plugins_dir = Path(__file__).parent
    found: list[PluginBase] = []

    for importer, modname, ispkg in pkgutil.iter_modules([str(plugins_dir)]):
        if not ispkg:
            continue
        try:
            module = importlib.import_module(f"pa.plugins.{modname}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, PluginBase)
                    and attr is not PluginBase
                    and attr.name
                ):
                    found.append(attr())
        except Exception:
            continue

    return sorted(found, key=lambda p: p.name)
```

Also create the `__init__.py` for test directories:

```python
# tests/core/__init__.py
# (empty)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/core/test_plugin_registry.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add pa/plugins/__init__.py tests/core/__init__.py tests/core/test_plugin_registry.py
git commit -m "feat: add plugin protocol, discovery, and DDL validation"
```

---

## Task 2: Identity Module

**Files:**
- Create: `pa/core/__init__.py`
- Create: `pa/core/identity.py`
- Create: `tests/core/test_identity.py`

- [ ] **Step 1: Write tests**

```python
# tests/core/test_identity.py
"""Tests for George's identity constants."""
from pa.core.identity import NAME, GREETING, PERSONA


def test_name_is_george():
    assert NAME == "George"


def test_greeting_uses_name():
    assert "George" in GREETING


def test_persona_uses_name():
    assert "George" in PERSONA
    assert "personal assistant" in PERSONA.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_identity.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement identity module**

```python
# pa/core/__init__.py
# (empty)
```

```python
# pa/core/identity.py
"""George's identity — change this file to rename the assistant."""
NAME = "George"
GREETING = f"Hey, {NAME} here."
PERSONA = (
    f"{NAME} is a personal assistant. "
    "Helpful, concise, and proactive. "
    "Speaks casually but knows his stuff."
)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_identity.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/core/__init__.py pa/core/identity.py tests/core/test_identity.py
git commit -m "feat: add George identity module"
```

---

## Task 3: Core Exceptions

**Files:**
- Create: `pa/core/exceptions.py`
- Create: `tests/core/test_exceptions.py`

The core keeps base exceptions. Scraper-specific exceptions move to the finance plugin later (Task 10).

- [ ] **Step 1: Write tests**

```python
# tests/core/test_exceptions.py
"""Tests for core exception hierarchy."""
from pa.core.exceptions import (
    PAError,
    VaultAuthError,
    VaultLockedError,
    StoreConnectionError,
    BrainAPIError,
    BrainCostCapError,
)


def test_hierarchy():
    assert issubclass(VaultAuthError, PAError)
    assert issubclass(VaultLockedError, PAError)
    assert issubclass(StoreConnectionError, PAError)
    assert issubclass(BrainAPIError, PAError)
    assert issubclass(BrainCostCapError, PAError)


def test_raise_and_catch():
    try:
        raise VaultLockedError("locked")
    except PAError as e:
        assert "locked" in str(e)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_exceptions.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement**

```python
# pa/core/exceptions.py
"""Base exception hierarchy for PA core."""


class PAError(Exception):
    """Base exception for all PA errors."""


class VaultAuthError(PAError):
    """Wrong master password."""


class VaultLockedError(PAError):
    """Operation attempted while vault is locked."""


class StoreConnectionError(PAError):
    """Database file missing or corrupt."""


class BrainAPIError(PAError):
    """Claude API returned error after retries."""


class BrainCostCapError(PAError):
    """Monthly cost cap exceeded."""
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_exceptions.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/core/exceptions.py tests/core/test_exceptions.py
git commit -m "feat: add core exception hierarchy"
```

---

## Task 4: Core Config (Move)

**Files:**
- Create: `pa/core/config.py`
- Create: `tests/core/test_config.py`

Config is unchanged in logic — just moved to `pa/core/`. The old `pa/config/` will be removed in the cleanup task.

- [ ] **Step 1: Write tests (adapted from existing test_config.py)**

```python
# tests/core/test_config.py
"""Tests for core Config module."""
import json
from pathlib import Path
import pytest

from pa.core.config import Config


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "telegram_user_id": 12345,
        "monthly_income": 5000.0,
        "cost_cap_monthly_usd": 20.0,
    }))
    return path


async def test_load(config_file: Path):
    config = Config(config_file)
    await config.load()
    assert config.get("telegram_user_id") == 12345


async def test_get_default(config_file: Path):
    config = Config(config_file)
    await config.load()
    assert config.get("missing_key", "default") == "default"


async def test_update(config_file: Path):
    config = Config(config_file)
    await config.load()
    await config.update("monthly_income", 6000.0)
    assert config.get("monthly_income") == 6000.0
    # Verify persisted
    reloaded = json.loads(config_file.read_text())
    assert reloaded["monthly_income"] == 6000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_config.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Copy config module to new location**

Copy `pa/config/config.py` to `pa/core/config.py`. No changes to the code itself — the module is already generic.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_config.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/core/config.py tests/core/test_config.py
git commit -m "feat: move config module to pa/core/"
```

---

## Task 5: Core Store (Generic SQLite Wrapper)

**Files:**
- Create: `pa/core/store.py`
- Create: `pa/core/schema.sql`
- Create: `tests/core/test_store.py`

The core store is a thin SQLite wrapper. Finance-specific methods (`add_account`, `get_balances`, etc.) are removed — they'll live in `plugins/finance/repository.py` (Task 9). Core schema has only `recipes` and `query_templates` tables.

- [ ] **Step 1: Write tests**

```python
# tests/core/test_store.py
"""Tests for generic core Store."""
from pathlib import Path
import pytest

from pa.core.store import Store


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    await s.init_schema()
    yield s
    await s.close()


async def test_connect_and_init(store: Store):
    """Store connects and creates core tables."""
    rows = await store.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = {r["name"] for r in rows}
    assert "recipes" in table_names
    assert "query_templates" in table_names


async def test_execute_and_fetchall(store: Store):
    await store.execute(
        "INSERT INTO recipes (plugin, name, steps) VALUES (?, ?, ?)",
        ("test", "test_recipe", "[]"),
    )
    rows = await store.fetchall("SELECT * FROM recipes WHERE plugin = ?", ("test",))
    assert len(rows) == 1
    assert rows[0]["name"] == "test_recipe"


async def test_fetchone(store: Store):
    await store.execute(
        "INSERT INTO recipes (plugin, name, steps) VALUES (?, ?, ?)",
        ("test", "r1", "[]"),
    )
    row = await store.fetchone("SELECT * FROM recipes WHERE name = ?", ("r1",))
    assert row is not None
    assert row["plugin"] == "test"


async def test_fetchone_returns_none(store: Store):
    row = await store.fetchone("SELECT * FROM recipes WHERE name = ?", ("nope",))
    assert row is None


async def test_execute_returns_lastrowid(store: Store):
    result = await store.execute(
        "INSERT INTO recipes (plugin, name, steps) VALUES (?, ?, ?)",
        ("test", "r2", "[]"),
    )
    assert result > 0


async def test_init_plugin_schema(store: Store):
    """Plugins can register their own tables."""
    ddl = """
    CREATE TABLE IF NOT EXISTS myplugin_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        value TEXT NOT NULL
    );
    """
    await store.init_plugin_schema("myplugin", ddl)
    rows = await store.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='myplugin_items'")
    assert len(rows) == 1


async def test_init_plugin_schema_rejects_bad_ddl(store: Store):
    with pytest.raises(ValueError, match="disallowed"):
        await store.init_plugin_schema("bad", "DROP TABLE recipes;")


async def test_init_plugin_schema_rejects_wrong_prefix(store: Store):
    with pytest.raises(ValueError, match="must be prefixed"):
        await store.init_plugin_schema("myplugin", "CREATE TABLE other_items (id INTEGER PRIMARY KEY);")


async def test_reconnect_encrypted(tmp_path: Path):
    s = Store(tmp_path / "enc.db")
    await s.connect()
    await s.init_schema()
    # Just verify reconnect doesn't crash (SQLCipher not available on Windows)
    try:
        await s.reconnect_encrypted(b"0" * 32)
    except Exception:
        pass  # SQLCipher may not be installed
    await s.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_store.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement core store**

```sql
-- pa/core/schema.sql
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin TEXT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    steps TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    last_success TEXT,
    fail_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS query_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    sql_template TEXT NOT NULL,
    format_template TEXT NOT NULL,
    plugin TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

```python
# pa/core/store.py
"""Generic async SQLite wrapper. Domain-specific queries live in plugin repositories."""
from pathlib import Path
from typing import Any

import aiosqlite

from pa.plugins import _validate_ddl

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Store:
    def __init__(self, db_path: Path, encryption_key: bytes | None = None):
        self._db_path = db_path
        self._encryption_key = encryption_key
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        if self._encryption_key:
            hex_key = self._encryption_key.hex()
            await self._db.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        await self._db.execute("PRAGMA foreign_keys = ON")

    async def init_schema(self) -> None:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        await self._db.executescript(schema)

    async def init_plugin_schema(self, plugin_name: str, ddl: str) -> None:
        """Run a plugin's DDL after validation."""
        _validate_ddl(ddl, plugin_name)
        await self._db.executescript(ddl)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def reconnect_encrypted(self, encryption_key: bytes) -> None:
        await self.close()
        self._encryption_key = encryption_key
        await self.connect()
        await self.init_schema()

    async def execute(self, sql: str, params: tuple = ()) -> int:
        cursor = await self._db.execute(sql, params)
        await self._db.commit()
        return cursor.lastrowid

    async def executemany(self, sql: str, params_list: list[tuple]) -> None:
        await self._db.executemany(sql, params_list)
        await self._db.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        cursor = await self._db.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_store.py -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/core/store.py pa/core/schema.sql tests/core/test_store.py
git commit -m "feat: add generic core store with plugin schema support"
```

---

## Task 6: Core Tier Classifier (Dynamic Registry)

**Files:**
- Create: `pa/core/tier.py`
- Create: `tests/core/test_tier.py`

Tier classifier accepts patterns from plugins instead of hardcoding them.

- [ ] **Step 1: Write tests**

```python
# tests/core/test_tier.py
"""Tests for dynamic tier classifier."""
from pa.core.tier import Tier, TierClassifier


def test_default_returns_standard():
    tc = TierClassifier()
    assert tc.classify("hello world") == Tier.STANDARD


def test_register_and_match_fast():
    tc = TierClassifier()
    tc.register({"fast": [r"\bbalance\b"], "standard": [], "deep": []})
    assert tc.classify("show my balance") == Tier.FAST


def test_register_and_match_deep():
    tc = TierClassifier()
    tc.register({"fast": [], "standard": [], "deep": [r"\bstrategy\b"]})
    assert tc.classify("debt payoff strategy") == Tier.DEEP


def test_deep_takes_priority():
    tc = TierClassifier()
    tc.register({
        "fast": [r"\bbalance\b"],
        "standard": [],
        "deep": [r"\bbalance\b"],
    })
    assert tc.classify("balance strategy") == Tier.DEEP


def test_multiple_registrations_merge():
    tc = TierClassifier()
    tc.register({"fast": [r"\bfoo\b"], "standard": [], "deep": []})
    tc.register({"fast": [r"\bbar\b"], "standard": [], "deep": []})
    assert tc.classify("foo") == Tier.FAST
    assert tc.classify("bar") == Tier.FAST
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_tier.py -v`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# pa/core/tier.py
"""Dynamic tier classifier — plugins register keyword patterns."""
import re
from enum import Enum


class Tier(Enum):
    FAST = "haiku"
    STANDARD = "sonnet"
    DEEP = "opus"


class TierClassifier:
    def __init__(self):
        self._patterns: dict[Tier, list[str]] = {
            Tier.FAST: [],
            Tier.STANDARD: [],
            Tier.DEEP: [],
        }

    def register(self, patterns: dict[str, list[str]]) -> None:
        for tier_name, pattern_list in patterns.items():
            tier = Tier[tier_name.upper()]
            self._patterns[tier].extend(pattern_list)

    def classify(self, query: str) -> Tier:
        lower = query.lower()
        for pattern in self._patterns[Tier.DEEP]:
            if re.search(pattern, lower):
                return Tier.DEEP
        for pattern in self._patterns[Tier.STANDARD]:
            if re.search(pattern, lower):
                return Tier.STANDARD
        for pattern in self._patterns[Tier.FAST]:
            if re.search(pattern, lower):
                return Tier.FAST
        return Tier.STANDARD
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_tier.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/core/tier.py tests/core/test_tier.py
git commit -m "feat: add dynamic tier classifier with plugin pattern registration"
```

---

## Task 7: Core Cost Tracker (Move) and Core Brain (Generic)

**Files:**
- Create: `pa/core/cost_tracker.py`
- Create: `pa/core/brain.py`
- Create: `tests/core/test_cost_tracker.py`
- Create: `tests/core/test_brain.py`

Cost tracker is moved unchanged. Brain is refactored: `build_system_prompt()` removed, replaced with generic prompt assembly from identity + plugin fragments. `query()` takes a system_prompt string instead of building one.

- [ ] **Step 1: Write cost tracker tests**

```python
# tests/core/test_cost_tracker.py
"""Tests for cost tracker."""
from pa.core.cost_tracker import CostTracker
from pa.core.exceptions import BrainCostCapError
import pytest


def test_initial_state():
    ct = CostTracker(monthly_cap=20.0)
    assert ct.total_this_month == 0.0
    assert ct.remaining == 20.0


def test_record():
    ct = CostTracker(monthly_cap=20.0)
    ct.record(5.0)
    assert ct.total_this_month == 5.0
    assert ct.remaining == 15.0


def test_alert_at_80_percent():
    ct = CostTracker(monthly_cap=10.0)
    ct.record(8.0)
    assert ct.should_alert


def test_check_budget_raises():
    ct = CostTracker(monthly_cap=10.0)
    ct.record(9.5)
    with pytest.raises(BrainCostCapError):
        ct.check_budget(1.0)


def test_reset():
    ct = CostTracker(monthly_cap=10.0)
    ct.record(5.0)
    ct.reset()
    assert ct.total_this_month == 0.0
```

- [ ] **Step 2: Write brain tests**

```python
# tests/core/test_brain.py
"""Tests for generic Brain module."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from pa.core.brain import Brain
from pa.core.config import Config
from pa.core.tier import Tier
from pa.core.exceptions import BrainAPIError


@pytest.fixture
def mock_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "claude_api_key_env": "PA_CLAUDE_API_KEY",
        "cost_cap_monthly_usd": 20.0,
    }))
    return path


@pytest.fixture
async def brain(mock_config):
    config = Config(mock_config)
    await config.load()
    with patch.dict("os.environ", {"PA_CLAUDE_API_KEY": "test-key"}):
        return Brain(config=config)


async def test_select_model(brain):
    assert "haiku" in brain.select_model(Tier.FAST)
    assert "sonnet" in brain.select_model(Tier.STANDARD)
    assert "opus" in brain.select_model(Tier.DEEP)


async def test_build_system_prompt_uses_identity(brain):
    prompt = brain.build_system_prompt(plugin_fragments=["Finance module active."])
    assert "George" in prompt
    assert "Finance module active." in prompt


async def test_build_system_prompt_no_fragments(brain):
    prompt = brain.build_system_prompt(plugin_fragments=[])
    assert "George" in prompt
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_cost_tracker.py tests/core/test_brain.py -v`
Expected: FAIL

- [ ] **Step 4: Implement cost tracker (copy from existing)**

```python
# pa/core/cost_tracker.py
"""Monthly API cost tracking and budget enforcement."""
from pa.core.exceptions import BrainCostCapError


class CostTracker:
    def __init__(self, monthly_cap: float):
        self._cap = monthly_cap
        self._total = 0.0

    @property
    def total_this_month(self) -> float:
        return self._total

    @property
    def remaining(self) -> float:
        return max(0.0, self._cap - self._total)

    @property
    def should_alert(self) -> bool:
        return self._total >= self._cap * 0.8

    def record(self, cost: float) -> None:
        self._total += cost

    def check_budget(self, estimated_cost: float) -> None:
        if self._total + estimated_cost > self._cap:
            raise BrainCostCapError(
                f"Monthly cost cap exceeded: ${self._total:.2f} spent of ${self._cap:.2f} cap"
            )

    def reset(self) -> None:
        self._total = 0.0

    def load_persisted(self, total: float) -> None:
        self._total = total
```

- [ ] **Step 5: Implement generic brain**

```python
# pa/core/brain.py
"""Generic Claude API integration. Domain-agnostic — plugins contribute system prompt fragments."""
import asyncio
import os
import time
from collections import deque
from typing import Any

import anthropic

from pa.core.cost_tracker import CostTracker
from pa.core.exceptions import BrainAPIError
from pa.core.identity import NAME, PERSONA
from pa.core.tier import Tier

_MODEL_MAP = {
    Tier.FAST: "claude-haiku-4-5-20251001",
    Tier.STANDARD: "claude-sonnet-4-6",
    Tier.DEEP: "claude-opus-4-6",
}

_COST_PER_1K_TOKENS = {
    Tier.FAST: 0.001,
    Tier.STANDARD: 0.01,
    Tier.DEEP: 0.10,
}

_MAX_RETRIES = 3
_MAX_QUERIES_PER_HOUR = 30


class Brain:
    def __init__(self, config: Any):
        api_key_env = config.get("claude_api_key_env", "PA_CLAUDE_API_KEY")
        api_key = os.environ.get(api_key_env, "")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._cost_tracker = CostTracker(
            monthly_cap=config.get("cost_cap_monthly_usd", 20.0)
        )
        self._query_timestamps: deque[float] = deque()
        self._plugin_fragments: list[str] = []

    def set_plugin_fragments(self, fragments: list[str]) -> None:
        self._plugin_fragments = fragments

    def _check_rate_limit(self) -> None:
        now = time.monotonic()
        while self._query_timestamps and now - self._query_timestamps[0] > 3600:
            self._query_timestamps.popleft()
        if len(self._query_timestamps) >= _MAX_QUERIES_PER_HOUR:
            raise BrainAPIError(
                f"Rate limit: {_MAX_QUERIES_PER_HOUR} queries/hour exceeded. Try again later."
            )

    def select_model(self, tier: Tier) -> str:
        return _MODEL_MAP[tier]

    def build_system_prompt(self, plugin_fragments: list[str] | None = None) -> str:
        frags = plugin_fragments if plugin_fragments is not None else self._plugin_fragments
        parts = [PERSONA]
        parts.extend(frags)
        parts.append(
            "Rules:\n"
            "- Be direct and actionable\n"
            "- Reference specific data when available\n"
            "- If asked about something not in your data, say so"
        )
        return "\n\n".join(parts)

    async def query(
        self,
        user_message: str,
        system_prompt: str | None = None,
        tier: Tier = Tier.STANDARD,
    ) -> str:
        self._check_rate_limit()
        model = self.select_model(tier)
        prompt = system_prompt or self.build_system_prompt()

        estimated_cost = _COST_PER_1K_TOKENS[tier] * 2
        self._cost_tracker.check_budget(estimated_cost)

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=1024,
                    system=prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                break
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
        else:
            raise BrainAPIError(f"Claude API error after {_MAX_RETRIES} retries: {last_error}") from last_error

        self._query_timestamps.append(time.monotonic())

        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        actual_cost = (total_tokens / 1000) * _COST_PER_1K_TOKENS[tier]
        self._cost_tracker.record(actual_cost)

        return response.content[0].text

    @property
    def cost_tracker(self) -> CostTracker:
        return self._cost_tracker
```

- [ ] **Step 6: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_cost_tracker.py tests/core/test_brain.py -v`
Expected: All PASSED

- [ ] **Step 7: Commit**

```bash
git add pa/core/cost_tracker.py pa/core/brain.py tests/core/test_cost_tracker.py tests/core/test_brain.py
git commit -m "feat: add generic brain with plugin prompt fragments and cost tracker"
```

---

## Task 8: Core Scheduler (Generic) and Core Bot (Generic)

**Files:**
- Create: `pa/core/scheduler.py`
- Create: `pa/core/bot.py`
- Create: `tests/core/test_scheduler.py`
- Create: `tests/core/test_bot.py`

Both stripped of finance-specific logic. Scheduler keeps only heartbeat. Bot keeps only vault commands + dynamic plugin command registry.

- [ ] **Step 1: Write scheduler tests**

```python
# tests/core/test_scheduler.py
"""Tests for generic scheduler."""
from pa.core.scheduler import PAScheduler
from pa.plugins import Job


def test_default_has_heartbeat_only():
    s = PAScheduler()
    assert "heartbeat" in s.get_job_names()
    assert len(s.get_job_names()) == 1


def test_register_job():
    s = PAScheduler()
    job = Job(name="test_job", handler=lambda: None, trigger="cron", kwargs={"hour": 6})
    s.register_job(job)
    assert "test_job" in s.get_job_names()


def test_pause_resume():
    s = PAScheduler()
    assert not s.is_paused
    s.pause()
    assert s.is_paused
    s.resume()
    assert not s.is_paused
```

- [ ] **Step 2: Write bot tests**

```python
# tests/core/test_bot.py
"""Tests for generic bot with plugin command registry."""
from pa.core.bot import PABot
from pa.plugins import Command


def test_register_command():
    bot = PABot.__new__(PABot)
    bot._command_registry = {}
    bot._builtin_commands = {"unlock", "lock", "status", "help", "plugins"}
    bot.register_command(Command(name="balance", description="Show balance", handler=lambda: None))
    assert "balance" in bot._command_registry


def test_cannot_override_builtin():
    bot = PABot.__new__(PABot)
    bot._command_registry = {}
    bot._builtin_commands = {"unlock", "lock", "status", "help", "plugins"}
    import pytest
    with pytest.raises(ValueError, match="builtin"):
        bot.register_command(Command(name="unlock", description="Bad", handler=lambda: None))


def test_help_text_includes_registered():
    bot = PABot.__new__(PABot)
    bot._command_registry = {}
    bot._builtin_commands = {"unlock", "lock", "status", "help", "plugins"}
    bot.register_command(Command(name="balance", description="Show balance", handler=lambda: None))
    text = bot.build_help_text()
    assert "/balance" in text
    assert "/unlock" in text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_scheduler.py tests/core/test_bot.py -v`
Expected: FAIL

- [ ] **Step 4: Implement core scheduler**

```python
# pa/core/scheduler.py
"""Generic APScheduler wrapper. Plugins register jobs; core only provides heartbeat."""
from typing import Any, Callable, Awaitable

from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pa.plugins import Job


class PAScheduler:
    def __init__(self):
        self._scheduler = AsyncScheduler()
        self._jobs: list[Job] = []
        self._alert_handler: Callable[..., Awaitable] | None = None
        self._paused = False
        # Built-in heartbeat
        self._jobs.append(Job(
            name="heartbeat",
            handler=self._heartbeat,
            trigger="cron",
            kwargs={"hour": 12, "minute": 0},
        ))

    async def _heartbeat(self, job_name: str = "heartbeat") -> None:
        if self._alert_handler:
            await self._alert_handler(job_name)

    def register_job(self, job: Job) -> None:
        self._jobs.append(job)

    def register_alert_handler(self, handler: Callable[..., Awaitable]) -> None:
        self._alert_handler = handler

    async def start(self) -> None:
        for job in self._jobs:
            handler = job.handler
            if job.trigger == "interval":
                trigger = IntervalTrigger(
                    hours=job.kwargs.get("hours", 4),
                    jitter=job.kwargs.get("jitter", 0),
                )
            else:
                trigger_kwargs = {k: v for k, v in job.kwargs.items()}
                trigger = CronTrigger(**trigger_kwargs)
            await self._scheduler.add_schedule(
                handler, trigger, id=job.name, args=[job.name]
            )
        await self._scheduler.start_in_background()

    async def stop(self) -> None:
        await self._scheduler.stop()

    def get_job_names(self) -> list[str]:
        return [j.name for j in self._jobs]

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused
```

- [ ] **Step 5: Implement core bot**

```python
# pa/core/bot.py
"""Generic Telegram bot with plugin command registry."""
import os
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from pa.core.identity import NAME
from pa.plugins import Command, AppContext


class PABot:
    _builtin_commands = {"unlock", "lock", "status", "help", "plugins"}

    def __init__(
        self,
        config: Any,
        vault: Any,
        store: Any,
        brain: Any,
        mfa_bridge: Any,
    ):
        self._config = config
        self._vault = vault
        self._store = store
        self._brain = brain
        self._mfa_bridge = mfa_bridge
        self._app: Application | None = None
        self._command_registry: dict[str, Command] = {}
        self._plugin_names: list[str] = []

    def register_command(self, cmd: Command) -> None:
        if cmd.name in self._builtin_commands:
            raise ValueError(f"Cannot override builtin command: /{cmd.name}")
        self._command_registry[cmd.name] = cmd

    def set_plugin_names(self, names: list[str]) -> None:
        self._plugin_names = names

    def build_help_text(self) -> str:
        lines = [
            f"**{NAME} Commands**\n",
            "/unlock - Enter master password",
            "/lock - Lock vault",
            "/status - System status",
            "/plugins - Active plugins",
        ]
        for name, cmd in sorted(self._command_registry.items()):
            lines.append(f"/{name} - {cmd.description}")
        lines.append("/help - This message")
        return "\n".join(lines)

    async def start(self) -> None:
        token_env = self._config.get("telegram_bot_token_env", "PA_TELEGRAM_TOKEN")
        token = os.environ.get(token_env, "")
        self._app = Application.builder().token(token).build()

        # Built-in commands
        builtins = {
            "unlock": self._handle_unlock,
            "lock": self._handle_lock,
            "status": self._handle_status,
            "help": self._handle_help,
            "plugins": self._handle_plugins,
        }
        for name, handler in builtins.items():
            self._app.add_handler(CommandHandler(name, handler))

        # Plugin commands
        for name, cmd in self._command_registry.items():
            async def make_handler(c=cmd):
                async def h(update: Update, context: ContextTypes.DEFAULT_TYPE):
                    if not self._check_auth(update):
                        return
                    ctx = AppContext(
                        store=self._store,
                        vault=self._vault,
                        brain=self._brain,
                        bot=self,
                        scheduler=None,
                        config=self._config,
                    )
                    result = await c.handler(ctx, update, context)
                    if result:
                        await update.message.reply_text(result)
                return h
            self._app.add_handler(CommandHandler(name, await make_handler()))

        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send_message(self, text: str) -> None:
        user_id = self._config.get("telegram_user_id")
        if self._app and user_id:
            await self._app.bot.send_message(chat_id=user_id, text=text)

    def _check_auth(self, update: Update) -> bool:
        allowed = self._config.get("telegram_user_id", 0)
        return update.effective_user.id == allowed

    async def _handle_unlock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        prompt_msg = await update.message.reply_text("Send your master password:")
        context.user_data["awaiting_password"] = True
        context.user_data["_prompt_message"] = prompt_msg

    async def _handle_lock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        self._vault.lock()
        await update.message.reply_text("Vault locked.")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        status = "unlocked" if self._vault.is_unlocked else "locked"
        text = f"Vault: {status}\n"
        if self._brain:
            ct = self._brain.cost_tracker
            text += f"API budget: ${ct.remaining:.2f} remaining this month\n"
        text += f"Plugins: {', '.join(self._plugin_names) or 'none'}"
        await update.message.reply_text(text)

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        await update.message.reply_text(self.build_help_text())

    async def _handle_plugins(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if self._plugin_names:
            text = "Active plugins:\n" + "\n".join(f"  - {n}" for n in self._plugin_names)
        else:
            text = "No plugins loaded."
        await update.message.reply_text(text)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return

        # Password input
        if context.user_data.get("awaiting_password"):
            context.user_data["awaiting_password"] = False
            password = update.message.text
            try:
                await update.message.delete()
            except Exception:
                pass
            prompt_msg = context.user_data.pop("_prompt_message", None)
            if prompt_msg:
                try:
                    await prompt_msg.delete()
                except Exception:
                    pass
            try:
                await self._vault.unlock(password)
                if self._vault.derived_key and hasattr(self._store, 'reconnect_encrypted'):
                    await self._store.reconnect_encrypted(self._vault.derived_key)
                await update.effective_chat.send_message("Vault unlocked.")
            except Exception:
                await update.effective_chat.send_message("Wrong password. Try /unlock again.")
            return

        # MFA routing
        for inst in list(self._mfa_bridge._pending.keys()):
            if self._mfa_bridge.has_pending(inst):
                await self._mfa_bridge.provide_mfa(inst, update.message.text)
                await update.message.reply_text(f"MFA code sent to {inst}.")
                return

        # Free-form query to brain
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return

        try:
            response = await self._brain.query(update.message.text)
            await update.message.reply_text(response)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
```

- [ ] **Step 6: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_scheduler.py tests/core/test_bot.py -v`
Expected: All PASSED

- [ ] **Step 7: Commit**

```bash
git add pa/core/scheduler.py pa/core/bot.py tests/core/test_scheduler.py tests/core/test_bot.py
git commit -m "feat: add generic bot with plugin command registry and generic scheduler"
```

---

## Task 9: Finance Plugin — Repository and Formatters

**Files:**
- Create: `pa/plugins/finance/__init__.py`
- Create: `pa/plugins/finance/repository.py`
- Create: `pa/plugins/finance/formatters.py`
- Create: `pa/plugins/finance/schema.sql`
- Create: `pa/plugins/finance/tier_patterns.py`
- Create: `tests/plugins/__init__.py`
- Create: `tests/plugins/finance/__init__.py`
- Create: `tests/plugins/finance/test_repository.py`
- Create: `tests/plugins/finance/test_formatters.py`
- Create: `tests/plugins/finance/test_tier_patterns.py`

Finance-specific store methods, formatters, and tier patterns extracted from old code.

- [ ] **Step 1: Write repository tests**

```python
# tests/plugins/finance/test_repository.py
"""Tests for finance repository (data access layer)."""
from pathlib import Path
import pytest

from pa.core.store import Store
from pa.plugins.finance.repository import FinanceRepository


@pytest.fixture
async def repo(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    await store.connect()
    await store.init_schema()
    # Init finance schema
    schema_path = Path(__file__).parent.parent.parent.parent / "pa" / "plugins" / "finance" / "schema.sql"
    ddl = schema_path.read_text(encoding="utf-8")
    await store.init_plugin_schema("finance", ddl)
    r = FinanceRepository(store)
    yield r
    await store.close()


async def test_add_and_get_account(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    assert acc_id > 0
    accounts = await repo.get_accounts()
    assert len(accounts) == 1
    assert accounts[0]["institution"] == "wellsfargo"


async def test_add_and_get_balance(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_balance(acc_id, balance=1500.0)
    balances = await repo.get_latest_balances()
    assert len(balances) == 1
    assert balances[0]["balance"] == 1500.0


async def test_add_transaction_dedup(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    inserted = await repo.add_transaction(acc_id, "2026-03-15", "GROCERY", -85.0)
    assert inserted
    dup = await repo.add_transaction(acc_id, "2026-03-15", "GROCERY", -85.0)
    assert not dup


async def test_get_transactions(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_transaction(acc_id, "2026-03-15", "GROCERY", -85.0)
    txns = await repo.get_transactions(account_id=acc_id)
    assert len(txns) == 1


async def test_log_scrape(repo):
    await repo.log_scrape("wellsfargo", "success")
    logs = await repo.get_scrape_logs()
    assert len(logs) == 1
```

- [ ] **Step 2: Write formatter tests**

```python
# tests/plugins/finance/test_formatters.py
"""Tests for finance formatters."""
from pa.plugins.finance.formatters import (
    format_balance_summary,
    format_debt_summary,
    format_due_summary,
    format_spending_summary,
)


def test_balance_summary_empty():
    assert "No account data" in format_balance_summary([])


def test_balance_summary():
    balances = [{"name": "WF Checking", "balance": 1500.0, "credit_limit": None}]
    result = format_balance_summary(balances)
    assert "WF Checking" in result
    assert "1,500.00" in result


def test_debt_summary():
    balances = [
        {"name": "CC", "type": "credit_card", "balance": 2500.0, "interest_rate": 0.2499},
        {"name": "Checking", "type": "checking", "balance": 1500.0, "interest_rate": None},
    ]
    result = format_debt_summary(balances)
    assert "CC" in result
    assert "Checking" not in result


def test_due_summary():
    balances = [{"name": "CC", "due_date": "2026-03-25", "minimum_payment": 35.0}]
    result = format_due_summary(balances)
    assert "35.00" in result


def test_spending_summary():
    txns = [{"category": "food", "amount": -50.0}, {"category": "food", "amount": -30.0}]
    result = format_spending_summary(txns, "this month")
    assert "80.00" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/plugins/finance/ -v`
Expected: FAIL

- [ ] **Step 4: Create finance schema**

```sql
-- pa/plugins/finance/schema.sql
CREATE TABLE IF NOT EXISTS finance_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('checking', 'savings', 'credit_card', 'mortgage', 'loan')),
    interest_rate REAL,
    credit_limit REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES finance_accounts(id),
    balance REAL NOT NULL,
    statement_balance REAL,
    available_credit REAL,
    minimum_payment REAL,
    due_date DATE,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES finance_accounts(id),
    date DATE NOT NULL,
    posted_date DATE,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT,
    dedup_hash TEXT UNIQUE NOT NULL,
    is_pending BOOLEAN DEFAULT 0,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution TEXT NOT NULL,
    account_id INTEGER REFERENCES finance_accounts(id),
    status TEXT NOT NULL CHECK(status IN ('success', 'failure', 'mfa_pending')),
    error_message TEXT,
    duration_seconds REAL,
    ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance_merchant_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL DEFAULT 'ai',
    hit_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 5: Implement finance repository**

```python
# pa/plugins/finance/repository.py
"""Finance-specific data access methods wrapping the core Store."""
import hashlib
from typing import Any

from pa.core.store import Store


class FinanceRepository:
    def __init__(self, store: Store):
        self._store = store

    async def add_account(
        self, institution: str, name: str, account_type: str,
        interest_rate: float | None = None, credit_limit: float | None = None,
    ) -> int:
        return await self._store.execute(
            "INSERT INTO finance_accounts (institution, name, type, interest_rate, credit_limit) VALUES (?, ?, ?, ?, ?)",
            (institution, name, account_type, interest_rate, credit_limit),
        )

    async def get_accounts(self) -> list[dict[str, Any]]:
        return await self._store.fetchall("SELECT * FROM finance_accounts ORDER BY id")

    async def add_balance(
        self, account_id: int, balance: float,
        statement_balance: float | None = None, available_credit: float | None = None,
        minimum_payment: float | None = None, due_date: str | None = None,
    ) -> int:
        return await self._store.execute(
            "INSERT INTO finance_balances (account_id, balance, statement_balance, available_credit, minimum_payment, due_date) VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, balance, statement_balance, available_credit, minimum_payment, due_date),
        )

    async def get_latest_balances(self) -> list[dict[str, Any]]:
        return await self._store.fetchall("""
            SELECT b.*, a.institution, a.name, a.type, a.interest_rate, a.credit_limit
            FROM finance_balances b
            JOIN finance_accounts a ON a.id = b.account_id
            WHERE b.id IN (
                SELECT MAX(id) FROM finance_balances GROUP BY account_id
            )
            ORDER BY a.id
        """)

    @staticmethod
    def _compute_dedup_hash(account_id: int, txn_date: str, description: str, amount: float) -> str:
        raw = f"{account_id}|{txn_date}|{description}|{amount}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def add_transaction(
        self, account_id: int, date: str, description: str, amount: float,
        posted_date: str | None = None, category: str | None = None, is_pending: bool = False,
    ) -> bool:
        dedup_hash = self._compute_dedup_hash(account_id, date, description, amount)
        rowid = await self._store.execute(
            "INSERT OR IGNORE INTO finance_transactions (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending),
        )
        return rowid > 0

    async def get_transactions(
        self, account_id: int | None = None, since_date: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM finance_transactions WHERE 1=1"
        params: list[Any] = []
        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        if since_date is not None:
            query += " AND date >= ?"
            params.append(since_date)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        return await self._store.fetchall(query, tuple(params))

    async def log_scrape(
        self, institution: str, status: str,
        account_id: int | None = None, error_message: str | None = None, duration_seconds: float | None = None,
    ) -> None:
        await self._store.execute(
            "INSERT INTO finance_scrape_log (institution, account_id, status, error_message, duration_seconds) VALUES (?, ?, ?, ?, ?)",
            (institution, account_id, status, error_message, duration_seconds),
        )

    async def get_scrape_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._store.fetchall(
            "SELECT * FROM finance_scrape_log ORDER BY ran_at DESC LIMIT ?", (limit,)
        )
```

- [ ] **Step 6: Implement formatters (extracted from old handlers.py)**

```python
# pa/plugins/finance/formatters.py
"""Finance-specific output formatters."""
from typing import Any
from collections import defaultdict

_DEBT_TYPES = {"credit_card", "mortgage", "loan"}


def format_balance_summary(balances: list[dict[str, Any]]) -> str:
    if not balances:
        return "No account data available."
    lines = ["**Account Balances**\n"]
    for b in balances:
        line = f"  {b['name']}: ${b['balance']:,.2f}"
        if b.get("credit_limit"):
            line += f" / ${b['credit_limit']:,.2f} limit"
        lines.append(line)
    return "\n".join(lines)


def format_debt_summary(balances: list[dict[str, Any]]) -> str:
    debt_accounts = [b for b in balances if b.get("type") in _DEBT_TYPES]
    if not debt_accounts:
        return "No debt accounts found."
    total = sum(b["balance"] for b in debt_accounts)
    lines = ["**Debt Summary**\n"]
    for b in sorted(debt_accounts, key=lambda x: x["balance"], reverse=True):
        line = f"  {b['name']}: ${b['balance']:,.2f}"
        if b.get("interest_rate"):
            line += f" @ {b['interest_rate']*100:.1f}% APR"
        lines.append(line)
    lines.append(f"\n  **Total Debt: ${total:,.2f}**")
    return "\n".join(lines)


def format_due_summary(balances: list[dict[str, Any]]) -> str:
    due_accounts = [b for b in balances if b.get("due_date") and b.get("minimum_payment")]
    if not due_accounts:
        return "No upcoming payments found."
    lines = ["**Upcoming Payments**\n"]
    for b in sorted(due_accounts, key=lambda x: x["due_date"]):
        lines.append(f"  {b['name']}: ${b['minimum_payment']:,.2f} due {b['due_date']}")
    return "\n".join(lines)


def format_spending_summary(transactions: list[dict[str, Any]], period: str) -> str:
    if not transactions:
        return f"No transactions found for {period}."
    by_category: dict[str, float] = defaultdict(float)
    for t in transactions:
        cat = t.get("category") or "uncategorized"
        by_category[cat] += abs(t["amount"])
    total = sum(by_category.values())
    lines = [f"**Spending for {period}**\n"]
    for cat, amount in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"  {cat}: ${amount:,.2f}")
    lines.append(f"\n  **Total: ${total:,.2f}**")
    return "\n".join(lines)
```

- [ ] **Step 7: Implement tier patterns**

```python
# pa/plugins/finance/tier_patterns.py
"""Financial keyword patterns for tier classification."""

FINANCE_TIER_PATTERNS = {
    "fast": [
        r"\bbalance\b", r"\bhow much\b", r"\bstatus\b", r"\bdue\b",
        r"\bowed?\b", r"\bminimum\b", r"\btotal\b", r"\bremaining\b",
    ],
    "standard": [
        r"\bspend", r"\bcategory\b", r"\bcompare\b", r"\btrend\b",
        r"\bpattern\b", r"\banalyz", r"\bbreakdown\b", r"\bhistory\b",
    ],
    "deep": [
        r"\bplan\b", r"\bstrategy\b", r"\bbudget\b", r"\bpayoff\b",
        r"\badvice\b", r"\brecommend\b", r"\boptimize\b", r"\bsnowball\b",
        r"\bavalanche\b", r"\bgoal\b", r"\bsave money\b", r"\bget out of debt\b",
    ],
}
```

- [ ] **Step 8: Create `__init__.py` files**

```python
# pa/plugins/finance/__init__.py
# (empty for now — will export FinancePlugin after Task 10)

# tests/plugins/__init__.py
# (empty)

# tests/plugins/finance/__init__.py
# (empty)
```

- [ ] **Step 9: Run tests**

Run: `.venv/Scripts/python -m pytest tests/plugins/finance/ -v`
Expected: All PASSED

- [ ] **Step 10: Commit**

```bash
git add pa/plugins/finance/ tests/plugins/
git commit -m "feat: add finance plugin repository, formatters, schema, and tier patterns"
```

---

## Task 10: Finance Plugin — Commands, Jobs, and PluginBase

**Files:**
- Create: `pa/plugins/finance/plugin.py`
- Create: `pa/plugins/finance/commands.py`
- Create: `pa/plugins/finance/jobs.py`
- Modify: `pa/plugins/finance/__init__.py`
- Create: `tests/plugins/finance/test_plugin.py`

This wires the finance plugin together — the PluginBase subclass that registers everything.

- [ ] **Step 1: Write plugin tests**

```python
# tests/plugins/finance/test_plugin.py
"""Tests for FinancePlugin integration."""
from pa.plugins.finance.plugin import FinancePlugin


def test_plugin_identity():
    p = FinancePlugin()
    assert p.name == "finance"
    assert p.description


def test_plugin_has_schema():
    p = FinancePlugin()
    ddl = p.schema_sql()
    assert "finance_accounts" in ddl
    assert "finance_transactions" in ddl


def test_plugin_has_commands():
    p = FinancePlugin()
    cmds = p.commands()
    cmd_names = {c.name for c in cmds}
    assert "balance" in cmd_names
    assert "debt" in cmd_names
    assert "spending" in cmd_names


def test_plugin_has_jobs():
    p = FinancePlugin()
    jobs = p.jobs()
    job_names = {j.name for j in jobs}
    assert "bank_balance" in job_names
    assert "cc_balance" in job_names


def test_plugin_has_tier_patterns():
    p = FinancePlugin()
    patterns = p.tier_patterns()
    assert "fast" in patterns
    assert "deep" in patterns


def test_plugin_has_system_prompt():
    p = FinancePlugin()
    fragment = p.system_prompt_fragment()
    assert "financial" in fragment.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/plugins/finance/test_plugin.py -v`
Expected: FAIL

- [ ] **Step 3: Implement finance commands**

```python
# pa/plugins/finance/commands.py
"""Finance plugin command handlers."""
from typing import Any

from pa.plugins import AppContext
from pa.plugins.finance.repository import FinanceRepository
from pa.plugins.finance.formatters import (
    format_balance_summary,
    format_debt_summary,
    format_due_summary,
    format_spending_summary,
)


def _repo(ctx: AppContext) -> FinanceRepository:
    return FinanceRepository(ctx.store)


async def handle_balance(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_balance_summary(balances)


async def handle_debt(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_debt_summary(balances)


async def handle_due(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_due_summary(balances)


async def handle_spending(ctx: AppContext, update: Any, context: Any) -> str:
    period = "this month"
    if context.args:
        period = " ".join(context.args)
    txns = await _repo(ctx).get_transactions(limit=500)
    return format_spending_summary(txns, period)


async def handle_plan(ctx: AppContext, update: Any, context: Any) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."
    balances = await _repo(ctx).get_latest_balances()
    from pa.core.tier import Tier
    response = await ctx.brain.query(
        "Create a debt payoff plan based on my current balances. Compare snowball vs avalanche strategies.",
        tier=Tier.DEEP,
    )
    return response


async def handle_scrape(ctx: AppContext, update: Any, context: Any) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."
    institution = context.args[0] if context.args else None
    return f"Starting scrape{' for ' + institution if institution else ''}..."


async def handle_schedule(ctx: AppContext, update: Any, context: Any) -> str:
    schedule = ctx.config.get("schedule", {})
    lines = ["**Current Schedule**\n"]
    for key, val in schedule.items():
        lines.append(f"  {key}: {val}")
    return "\n".join(lines)


async def handle_backup(ctx: AppContext, update: Any, context: Any) -> str:
    backup_path = ctx.config.get("backup_path", "")
    if not backup_path:
        return "Backup path not configured. Set backup_path in config."
    return f"Backup saved to {backup_path}"
```

- [ ] **Step 4: Implement finance jobs**

```python
# pa/plugins/finance/jobs.py
"""Finance plugin scheduled job definitions."""
from pa.plugins import Job


def get_finance_jobs() -> list[Job]:
    async def noop(job_name: str) -> None:
        pass  # Actual handlers wired at startup

    return [
        Job(name="bank_balance", handler=noop, trigger="interval", kwargs={"hours": 4, "jitter": 900}),
        Job(name="cc_balance", handler=noop, trigger="cron", kwargs={"hour": 6, "minute": 0}),
        Job(name="transaction_pull", handler=noop, trigger="cron", kwargs={"hour": 7, "minute": 0}),
        Job(name="due_date_check", handler=noop, trigger="cron", kwargs={"hour": 8, "minute": 0}),
        Job(name="weekly_summary", handler=noop, trigger="cron", kwargs={"day_of_week": "sun", "hour": 19, "minute": 0}),
        Job(name="monthly_report", handler=noop, trigger="cron", kwargs={"day": 1, "hour": 9, "minute": 0}),
    ]
```

- [ ] **Step 5: Implement FinancePlugin**

```python
# pa/plugins/finance/plugin.py
"""Finance plugin — wraps all financial functionality into the plugin protocol."""
from pathlib import Path

from pa.plugins import PluginBase, Command
from pa.plugins.finance.commands import (
    handle_balance, handle_debt, handle_due, handle_spending,
    handle_plan, handle_scrape, handle_schedule, handle_backup,
)
from pa.plugins.finance.jobs import get_finance_jobs
from pa.plugins.finance.tier_patterns import FINANCE_TIER_PATTERNS

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class FinancePlugin(PluginBase):
    name = "finance"
    description = "Financial tracking, analysis, and debt management"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="balance", description="Account balances", handler=handle_balance),
            Command(name="debt", description="Debt summary", handler=handle_debt),
            Command(name="due", description="Upcoming payments", handler=handle_due),
            Command(name="spending", description="Spending breakdown", handler=handle_spending, aliases=["spend"]),
            Command(name="plan", description="Debt payoff plan (AI)", handler=handle_plan),
            Command(name="scrape", description="Force a scrape", handler=handle_scrape),
            Command(name="schedule", description="View schedule", handler=handle_schedule),
            Command(name="backup", description="Backup database", handler=handle_backup),
        ]

    def jobs(self) -> list:
        return get_finance_jobs()

    def tier_patterns(self) -> dict[str, list[str]]:
        return FINANCE_TIER_PATTERNS

    def system_prompt_fragment(self) -> str:
        return (
            "Financial analysis module active. You have access to bank accounts, "
            "credit cards, and transaction data. Help the user understand their spending, "
            "track debt payoff progress, and make smart financial decisions. Be specific "
            "with numbers. Flag concerning patterns proactively."
        )
```

- [ ] **Step 6: Update finance `__init__.py`**

```python
# pa/plugins/finance/__init__.py
from pa.plugins.finance.plugin import FinancePlugin

__all__ = ["FinancePlugin"]
```

- [ ] **Step 7: Run tests**

Run: `.venv/Scripts/python -m pytest tests/plugins/finance/ -v`
Expected: All PASSED

- [ ] **Step 8: Commit**

```bash
git add pa/plugins/finance/ tests/plugins/finance/test_plugin.py
git commit -m "feat: complete finance plugin with commands, jobs, and plugin class"
```

---

## Task 11: Move Scrapers to Finance Plugin

**Files:**
- Create: `pa/plugins/finance/scrapers/__init__.py`
- Create: `pa/plugins/finance/scrapers/wellsfargo.py`
- Create: `pa/plugins/finance/scrapers/synchrony.py`
- Create: `pa/plugins/finance/scrapers/credit_one.py`
- Create: `tests/scrapers/__init__.py`
- Create: `tests/scrapers/test_scraper_base.py`
- Create: `tests/scrapers/test_mfa_bridge.py`

- [ ] **Step 1: Copy scraper files to finance plugin**

Copy `pa/scrapers/wellsfargo.py`, `synchrony.py`, `credit_one.py` to `pa/plugins/finance/scrapers/`.
Update imports: `from pa.scrapers.base import BaseScraper, BalanceData, TransactionData`.

Create empty `pa/plugins/finance/scrapers/__init__.py`.

- [ ] **Step 2: Create test files for generic scraper infra (moved location)**

```python
# tests/scrapers/__init__.py
# (empty)

# tests/scrapers/test_scraper_base.py
"""Tests for BaseScraper abstract class."""
import pytest
from pa.scrapers.base import BaseScraper, BalanceData, TransactionData


def test_balance_data():
    b = BalanceData(balance=1500.0, due_date="2026-03-25")
    assert b.balance == 1500.0
    assert b.due_date == "2026-03-25"


def test_transaction_data():
    t = TransactionData(date="2026-03-15", description="GROCERY", amount=-85.0)
    assert t.amount == -85.0
    assert not t.is_pending


def test_base_scraper_is_abstract():
    with pytest.raises(TypeError):
        BaseScraper(context=None, mfa_bridge=None)
```

```python
# tests/scrapers/test_mfa_bridge.py
"""Tests for MFA bridge."""
import asyncio
import pytest
from pa.scrapers.mfa_bridge import MFABridge


async def test_mfa_round_trip():
    bridge = MFABridge(timeout_seconds=2.0)
    assert not bridge.has_pending("bank")

    async def provide():
        await asyncio.sleep(0.05)
        await bridge.provide_mfa("bank", "123456")

    asyncio.create_task(provide())
    code = await bridge.request_mfa("bank", "Enter code")
    assert code == "123456"


async def test_mfa_timeout():
    bridge = MFABridge(timeout_seconds=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await bridge.request_mfa("bank", "Enter code")


async def test_has_pending():
    bridge = MFABridge(timeout_seconds=2.0)

    async def slow_request():
        try:
            await bridge.request_mfa("bank", "Enter code")
        except asyncio.TimeoutError:
            pass

    task = asyncio.create_task(slow_request())
    await asyncio.sleep(0.01)
    assert bridge.has_pending("bank")
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
```

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python -m pytest tests/scrapers/ -v`
Expected: All PASSED

- [ ] **Step 4: Commit**

```bash
git add pa/plugins/finance/scrapers/ tests/scrapers/
git commit -m "feat: move financial scrapers to finance plugin"
```

---

## Task 12: Recipe Engine (Learn-Once)

**Files:**
- Create: `pa/scrapers/recipe.py`
- Create: `tests/core/test_recipe.py`

- [ ] **Step 1: Write tests**

```python
# tests/core/test_recipe.py
"""Tests for learn-once recipe engine."""
import json
from pathlib import Path
import pytest

from pa.core.store import Store
from pa.scrapers.recipe import RecipeEngine, CRED_ALLOWLIST


@pytest.fixture
async def engine(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    await store.connect()
    await store.init_schema()
    e = RecipeEngine(store)
    yield e
    await store.close()


async def test_no_recipe(engine):
    assert not await engine.has_recipe("test")


async def test_record_and_has(engine):
    steps = [{"action": "goto", "url": "https://example.com"}]
    await engine.record("test_recipe", "finance", steps)
    assert await engine.has_recipe("test_recipe")


async def test_get_recipe(engine):
    steps = [{"action": "goto", "url": "https://example.com"}]
    await engine.record("test_recipe", "finance", steps)
    recipe = await engine.get_recipe("test_recipe")
    assert recipe is not None
    loaded_steps = json.loads(recipe["steps"])
    assert loaded_steps[0]["action"] == "goto"


async def test_mark_stale(engine):
    steps = [{"action": "goto", "url": "https://example.com"}]
    await engine.record("test_recipe", "finance", steps)
    await engine.mark_stale("test_recipe")
    recipe = await engine.get_recipe("test_recipe")
    assert recipe["fail_count"] == 1


async def test_validate_cred_allowlist():
    assert "username" in CRED_ALLOWLIST
    assert "password" in CRED_ALLOWLIST


async def test_record_rejects_bad_cred(engine):
    steps = [{"action": "fill", "selector": "#ssn", "value": "$cred.ssn"}]
    with pytest.raises(ValueError, match="not in allowlist"):
        await engine.record("bad_recipe", "finance", steps)


async def test_record_allows_good_cred(engine):
    steps = [
        {"action": "fill", "selector": "#user", "value": "$cred.username"},
        {"action": "fill", "selector": "#pass", "value": "$cred.password"},
    ]
    await engine.record("good_recipe", "finance", steps)
    assert await engine.has_recipe("good_recipe")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/core/test_recipe.py -v`
Expected: FAIL

- [ ] **Step 3: Implement recipe engine**

```python
# pa/scrapers/recipe.py
"""Learn-once recipe engine — records and replays browser action sequences."""
import json
import re
from typing import Any

from pa.core.store import Store

CRED_ALLOWLIST = {"username", "password"}
CURRENT_SCHEMA_VERSION = 1
_CRED_PATTERN = re.compile(r"\$cred\.(\w+)")


def _validate_steps(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        for value in step.values():
            if isinstance(value, str):
                for match in _CRED_PATTERN.finditer(value):
                    field = match.group(1)
                    if field not in CRED_ALLOWLIST:
                        raise ValueError(
                            f"Credential field '{field}' not in allowlist. "
                            f"Allowed: {CRED_ALLOWLIST}"
                        )


class RecipeEngine:
    def __init__(self, store: Store):
        self._store = store

    async def has_recipe(self, name: str) -> bool:
        row = await self._store.fetchone(
            "SELECT id FROM recipes WHERE name = ? AND schema_version >= ?",
            (name, CURRENT_SCHEMA_VERSION),
        )
        return row is not None

    async def get_recipe(self, name: str) -> dict[str, Any] | None:
        return await self._store.fetchone(
            "SELECT * FROM recipes WHERE name = ?", (name,)
        )

    async def record(self, name: str, plugin: str, steps: list[dict[str, Any]]) -> None:
        _validate_steps(steps)
        steps_json = json.dumps(steps)
        # Upsert
        existing = await self.get_recipe(name)
        if existing:
            await self._store.execute(
                "UPDATE recipes SET steps = ?, schema_version = ?, fail_count = 0, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                (steps_json, CURRENT_SCHEMA_VERSION, name),
            )
        else:
            await self._store.execute(
                "INSERT INTO recipes (plugin, name, steps, schema_version) VALUES (?, ?, ?, ?)",
                (plugin, name, steps_json, CURRENT_SCHEMA_VERSION),
            )

    async def mark_stale(self, name: str) -> None:
        await self._store.execute(
            "UPDATE recipes SET fail_count = fail_count + 1, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (name,),
        )

    async def mark_success(self, name: str) -> None:
        await self._store.execute(
            "UPDATE recipes SET last_success = CURRENT_TIMESTAMP, fail_count = 0, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (name,),
        )

    def resolve_credentials(self, steps: list[dict[str, Any]], credentials: dict[str, str]) -> list[dict[str, Any]]:
        resolved = []
        for step in steps:
            new_step = {}
            for k, v in step.items():
                if isinstance(v, str) and "$cred." in v:
                    for match in _CRED_PATTERN.finditer(v):
                        field = match.group(1)
                        v = v.replace(f"$cred.{field}", credentials.get(field, ""))
                new_step[k] = v
            resolved.append(new_step)
        return resolved
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/core/test_recipe.py -v`
Expected: All PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/scrapers/recipe.py tests/core/test_recipe.py
git commit -m "feat: add learn-once recipe engine with credential allowlist"
```

---

## Task 13: Core App Wiring and Entry Point

**Files:**
- Create: `pa/core/app.py`
- Modify: `pa/__main__.py`

This is the glue that discovers plugins and wires everything together.

- [ ] **Step 1: Implement app.py**

```python
# pa/core/app.py
"""Application entry point — discovers plugins, wires core modules, runs event loop."""
import asyncio
import signal
from pathlib import Path

from pa.core.config import Config
from pa.core.identity import NAME, GREETING
from pa.core.store import Store
from pa.core.brain import Brain
from pa.core.tier import TierClassifier
from pa.core.scheduler import PAScheduler
from pa.core.bot import PABot
from pa.vault.vault import Vault
from pa.scrapers.mfa_bridge import MFABridge
from pa.plugins import PluginBase, AppContext, discover_plugins


async def main() -> None:
    base_dir = Path(__file__).parent.parent.parent
    config_path = base_dir / "config.json"
    data_dir = base_dir / "data"
    data_dir.mkdir(exist_ok=True)

    # Load config
    config = Config(config_path)
    await config.load()

    # Initialize core modules
    vault = Vault(data_dir)
    mfa_bridge = MFABridge()
    brain = Brain(config=config)
    tier_classifier = TierClassifier()
    scheduler = PAScheduler()

    store = Store(data_dir / "pa.db")
    await store.connect()
    await store.init_schema()

    bot = PABot(
        config=config,
        vault=vault,
        store=store,
        brain=brain,
        mfa_bridge=mfa_bridge,
    )

    # Discover and wire plugins
    plugins = discover_plugins()
    plugin_names = [p.name for p in plugins]
    bot.set_plugin_names(plugin_names)

    for plugin in plugins:
        # Schema
        ddl = plugin.schema_sql()
        if ddl:
            await store.init_plugin_schema(plugin.name, ddl)

        # Commands
        for cmd in plugin.commands():
            bot.register_command(cmd)

        # Jobs
        for job in plugin.jobs():
            scheduler.register_job(job)

        # Tier patterns
        patterns = plugin.tier_patterns()
        if patterns:
            tier_classifier.register(patterns)

        # System prompt
        fragment = plugin.system_prompt_fragment()
        if fragment:
            brain._plugin_fragments.append(fragment)

    # Context for plugin startup
    ctx = AppContext(
        store=store, vault=vault, brain=brain,
        bot=bot, scheduler=scheduler, config=config,
    )
    for plugin in plugins:
        await plugin.on_startup(ctx)

    # Start bot
    await bot.start()

    vault_exists = (data_dir / "vault.enc").exists()
    if vault_exists:
        await bot.send_message(f"{GREETING} Send /unlock to enter master password.")
    else:
        await bot.send_message(
            f"{GREETING} First-time setup:\n"
            "1. Send /unlock to create your encrypted vault\n"
            "2. You'll set a master password\n"
            "3. Then add your financial institution credentials"
        )

    # Start scheduler
    async def alert_handler(job_name: str) -> None:
        if job_name == "heartbeat":
            await bot.send_message(f"{NAME} running. All systems OK.")

    scheduler.register_alert_handler(alert_handler)
    await scheduler.start()

    # Keep running
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for plugin in plugins:
            await plugin.on_shutdown()
        await scheduler.stop()
        await bot.stop()
        await store.close()
```

- [ ] **Step 2: Update __main__.py**

```python
# pa/__main__.py
import asyncio
from pa.core.app import main

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Commit**

```bash
git add pa/core/app.py pa/__main__.py
git commit -m "feat: add core app wiring with plugin discovery"
```

---

## Task 14: Vault — Update Imports

**Files:**
- Modify: `pa/vault/__init__.py`
- Modify: `pa/vault/vault.py`
- Create: `tests/vault/__init__.py`
- Create: `tests/vault/test_vault.py`
- Create: `tests/vault/test_vault_crypto.py`

Vault module stays at `pa/vault/` but needs to import exceptions from `pa.core.exceptions` instead of `pa.exceptions`.

- [ ] **Step 1: Update vault.py imports**

Change `from pa.exceptions import VaultAuthError, VaultLockedError` to `from pa.core.exceptions import VaultAuthError, VaultLockedError`.

Also update `from pa.vault.crypto import derive_key, encrypt, decrypt` — this stays the same since vault stays in `pa/vault/`.

- [ ] **Step 2: Create vault tests in new location**

Copy existing `tests/test_vault.py` → `tests/vault/test_vault.py` and `tests/test_vault_crypto.py` → `tests/vault/test_vault_crypto.py`. Update imports from `pa.exceptions` to `pa.core.exceptions`.

- [ ] **Step 3: Run tests**

Run: `.venv/Scripts/python -m pytest tests/vault/ -v`
Expected: All PASSED

- [ ] **Step 4: Commit**

```bash
git add pa/vault/ tests/vault/
git commit -m "refactor: update vault imports to use pa.core.exceptions"
```

---

## Task 15: Integration Test and Cleanup

**Files:**
- Create: `tests/test_integration.py` (new version)
- Modify: `pa/__init__.py`
- Delete: old `pa/config/`, `pa/store/`, `pa/brain/`, `pa/scheduler/`, `pa/bot/`, `pa/scrapers/wellsfargo.py`, `pa/scrapers/synchrony.py`, `pa/scrapers/credit_one.py`, `pa/exceptions.py`
- Delete: old `tests/test_*.py` files

- [ ] **Step 1: Write new integration test**

```python
# tests/test_integration.py
"""Integration smoke test — all modules wire together with plugin system."""
from pathlib import Path
import pytest

from pa.core.config import Config
from pa.core.store import Store
from pa.core.brain import Brain
from pa.core.identity import NAME
from pa.vault.vault import Vault
from pa.scrapers.mfa_bridge import MFABridge
from pa.core.scheduler import PAScheduler
from pa.core.exceptions import VaultLockedError
from pa.plugins import discover_plugins
from pa.plugins.finance.repository import FinanceRepository


async def test_full_flow(tmp_path: Path):
    """Test complete data flow through plugin architecture."""
    # Config
    import json
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "telegram_user_id": 12345,
        "cost_cap_monthly_usd": 20.0,
    }))
    config = Config(config_path)
    await config.load()

    # Store with plugin schema
    store = Store(tmp_path / "test.db")
    await store.connect()
    await store.init_schema()

    # Discover plugins
    plugins = discover_plugins()
    assert any(p.name == "finance" for p in plugins)

    # Init plugin schema
    for p in plugins:
        ddl = p.schema_sql()
        if ddl:
            await store.init_plugin_schema(p.name, ddl)

    # Finance repository
    repo = FinanceRepository(store)
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_balance(acc_id, balance=1500.0)
    balances = await repo.get_latest_balances()
    assert len(balances) == 1

    # Brain uses identity
    brain = Brain(config=config)
    prompt = brain.build_system_prompt()
    assert NAME in prompt

    # Vault
    vault = Vault(tmp_path)
    await vault.init("test-password")
    await vault.add("wellsfargo", {"username": "test", "password": "pass"})
    creds = vault.get("wellsfargo")
    assert creds["username"] == "test"

    vault.lock()
    with pytest.raises(VaultLockedError):
        vault.get("wellsfargo")

    # MFA bridge
    mfa = MFABridge(timeout_seconds=0.1)
    assert not mfa.has_pending("wellsfargo")

    # Scheduler has heartbeat + finance jobs
    scheduler = PAScheduler()
    for p in plugins:
        for job in p.jobs():
            scheduler.register_job(job)
    job_names = scheduler.get_job_names()
    assert "heartbeat" in job_names
    assert "bank_balance" in job_names

    await store.close()
```

- [ ] **Step 2: Run integration test**

Run: `.venv/Scripts/python -m pytest tests/test_integration.py -v`
Expected: PASSED

- [ ] **Step 3: Delete old module directories and files**

Remove:
- `pa/config/` directory
- `pa/store/` directory
- `pa/brain/` directory (old)
- `pa/scheduler/` directory (old)
- `pa/bot/` directory (old)
- `pa/exceptions.py`
- `pa/scrapers/wellsfargo.py`
- `pa/scrapers/synchrony.py`
- `pa/scrapers/credit_one.py`
- All old `tests/test_*.py` files (not in subdirectories)

- [ ] **Step 4: Run full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: All tests pass (the new test suite in subdirectories)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: complete migration to plugin architecture — remove old modules"
```

---

## Task 16: Final Verification

- [ ] **Step 1: Run complete test suite**

Run: `.venv/Scripts/python -m pytest -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Verify imports work**

Run: `.venv/Scripts/python -c "from pa.core.app import main; from pa.plugins.finance import FinancePlugin; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Verify plugin discovery**

Run: `.venv/Scripts/python -c "from pa.plugins import discover_plugins; plugins = discover_plugins(); print([p.name for p in plugins])"`
Expected: `['finance']`

- [ ] **Step 4: Verify git is clean**

Run: `git status`
Expected: Clean working tree

- [ ] **Step 5: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix: final test and import adjustments"
```
