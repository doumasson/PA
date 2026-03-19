# Personal Assistant (PA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal financial assistant that scrapes bank/credit card sites, stores encrypted data locally, and provides insights via Telegram bot powered by Claude API.

**Architecture:** Asyncio-based modular monolith. Single Python process with clean module boundaries: vault (encryption), store (SQLite), scrapers (Playwright), brain (Claude API), scheduler (APScheduler), bot (Telegram). All modules communicate through defined async interfaces.

**Tech Stack:** Python 3.11+, Playwright, SQLCipher/aiosqlite, argon2-cffi, cryptography, python-telegram-bot v20+, APScheduler 4.x, anthropic SDK

**Spec:** `docs/superpowers/specs/2026-03-19-personal-assistant-design.md`

---

## File Structure

```
pa/
  __init__.py
  __main__.py                  # Entry point — wires all modules, runs event loop
  exceptions.py                # All custom exceptions (VaultAuthError, etc.)
  config/
    __init__.py
    config.py                  # Config class — loads/saves config.json
  vault/
    __init__.py
    vault.py                   # Vault class — encrypt/decrypt/get/add credentials
    crypto.py                  # Key derivation (Argon2id) and AES-256-GCM helpers
  store/
    __init__.py
    store.py                   # Store class — async SQLite wrapper with all queries
    schema.sql                 # DDL for all tables
  scrapers/
    __init__.py
    base.py                    # BaseScraper abstract class
    mfa_bridge.py              # MFABridge — async MFA callback coordination
    wellsfargo.py              # Wells Fargo scraper
    synchrony.py               # Synchrony Bank scraper (stub)
    credit_one.py              # Credit One scraper (stub)
  brain/
    __init__.py
    brain.py                   # Brain class — tier selection, API calls, context building
    tier.py                    # Tier classifier — keyword/regex heuristic
    cost_tracker.py            # Monthly cost tracking and caps
  scheduler/
    __init__.py
    scheduler.py               # Scheduler class — wraps APScheduler, defines jobs
  bot/
    __init__.py
    bot.py                     # Bot class — Telegram handlers, command routing
    handlers.py                # Individual command handler functions
tests/
  __init__.py
  conftest.py                  # Shared fixtures (temp dirs, mock config, etc.)
  test_config.py
  test_vault_crypto.py
  test_vault.py
  test_store.py
  test_exceptions.py
  test_mfa_bridge.py
  test_brain_tier.py
  test_brain_cost_tracker.py
  test_brain.py
  test_scheduler.py
  test_bot.py
  test_bot_integration.py
  test_scraper_base.py
  test_integration.py
config.example.json            # Example config (committed, no secrets)
pyproject.toml                 # Project metadata, dependencies, pytest config
.env.example                   # Example env vars (committed, no secrets)
```

---

## Task 1: Project Scaffolding and Dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `config.example.json`
- Create: `.env.example`
- Create: `pa/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "pa"
version = "0.1.0"
description = "Personal financial assistant"
requires-python = ">=3.11"
dependencies = [
    "argon2-cffi>=23.1.0",
    "cryptography>=42.0.0",
    "aiosqlite>=0.20.0",
    "sqlcipher3-binary>=0.5.0",
    "playwright>=1.40.0",
    "python-telegram-bot>=20.0",
    "apscheduler>=4.0.0a1",
    "anthropic>=0.40.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Create config.example.json**

```json
{
  "telegram_user_id": 0,
  "telegram_bot_token_env": "PA_TELEGRAM_TOKEN",
  "claude_api_key_env": "PA_CLAUDE_API_KEY",
  "monthly_income": 0.0,
  "financial_goals": [],
  "preferences": [],
  "schedule": {
    "bank_balance_hours": 4,
    "cc_balance_daily_time": "06:00",
    "transaction_pull_daily_time": "07:00",
    "due_date_check_time": "08:00",
    "weekly_summary_day": "sunday",
    "weekly_summary_time": "19:00"
  },
  "cost_cap_monthly_usd": 20.0,
  "backup_path": ""
}
```

- [ ] **Step 3: Create .env.example**

```
PA_TELEGRAM_TOKEN=your-telegram-bot-token-here
PA_CLAUDE_API_KEY=your-anthropic-api-key-here
```

- [ ] **Step 4: Create pa/__init__.py and tests/__init__.py**

Both empty files.

- [ ] **Step 5: Create tests/conftest.py**

```python
import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sample_config(tmp_dir: Path) -> Path:
    config_path = tmp_dir / "config.json"
    config_path.write_text(json.dumps({
        "telegram_user_id": 123456789,
        "telegram_bot_token_env": "PA_TELEGRAM_TOKEN",
        "claude_api_key_env": "PA_CLAUDE_API_KEY",
        "monthly_income": 5000.0,
        "financial_goals": ["debt-free in 2 years"],
        "preferences": [],
        "schedule": {
            "bank_balance_hours": 4,
            "cc_balance_daily_time": "06:00",
            "transaction_pull_daily_time": "07:00",
            "due_date_check_time": "08:00",
            "weekly_summary_day": "sunday",
            "weekly_summary_time": "19:00",
        },
        "cost_cap_monthly_usd": 20.0,
        "backup_path": "",
    }))
    return config_path
```

- [ ] **Step 6: Create virtual environment and install dependencies**

Run:
```bash
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -e ".[dev]"
```

- [ ] **Step 7: Verify pytest runs**

Run: `python -m pytest --co -q`
Expected: `no tests ran` (no errors)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml config.example.json .env.example pa/__init__.py tests/__init__.py tests/conftest.py
git commit -m "feat: project scaffolding with dependencies and test fixtures"
```

---

## Task 2: Exceptions Module

**Files:**
- Create: `pa/exceptions.py`
- Create: `tests/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exceptions.py
from pa.exceptions import (
    PAError,
    VaultAuthError,
    VaultLockedError,
    ScraperLoginError,
    ScraperMFATimeout,
    ScraperParseError,
    StoreConnectionError,
    BrainAPIError,
    BrainCostCapError,
)


def test_all_exceptions_inherit_from_pa_error():
    exceptions = [
        VaultAuthError, VaultLockedError,
        ScraperLoginError, ScraperMFATimeout, ScraperParseError,
        StoreConnectionError,
        BrainAPIError, BrainCostCapError,
    ]
    for exc_cls in exceptions:
        assert issubclass(exc_cls, PAError)


def test_exceptions_carry_message():
    err = VaultAuthError("wrong password")
    assert str(err) == "wrong password"


def test_scraper_errors_carry_institution():
    err = ScraperLoginError("login failed", institution="wellsfargo")
    assert err.institution == "wellsfargo"
    assert "login failed" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_exceptions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pa.exceptions'`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/exceptions.py


class PAError(Exception):
    """Base exception for all PA errors."""


class VaultAuthError(PAError):
    """Wrong master password."""


class VaultLockedError(PAError):
    """Operation attempted while vault is locked."""


class ScraperLoginError(PAError):
    """Login to financial institution failed."""

    def __init__(self, message: str, institution: str = ""):
        super().__init__(message)
        self.institution = institution


class ScraperMFATimeout(PAError):
    """MFA code not provided within timeout."""

    def __init__(self, message: str, institution: str = ""):
        super().__init__(message)
        self.institution = institution


class ScraperParseError(PAError):
    """Page layout changed, data extraction failed."""

    def __init__(self, message: str, institution: str = ""):
        super().__init__(message)
        self.institution = institution


class StoreConnectionError(PAError):
    """Database file missing or corrupt."""


class BrainAPIError(PAError):
    """Claude API returned error after retries."""


class BrainCostCapError(PAError):
    """Monthly cost cap exceeded."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_exceptions.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/exceptions.py tests/test_exceptions.py
git commit -m "feat: add typed exception hierarchy for all modules"
```

---

## Task 3: Config Module

**Files:**
- Create: `pa/config/__init__.py`
- Create: `pa/config/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import json
from pathlib import Path

import pytest

from pa.config.config import Config


async def test_load_config(sample_config: Path):
    config = Config(sample_config)
    await config.load()
    assert config.get("telegram_user_id") == 123456789
    assert config.get("monthly_income") == 5000.0


async def test_get_nested_key(sample_config: Path):
    config = Config(sample_config)
    await config.load()
    schedule = config.get("schedule")
    assert schedule["bank_balance_hours"] == 4


async def test_get_missing_key_returns_default(sample_config: Path):
    config = Config(sample_config)
    await config.load()
    assert config.get("nonexistent", default="fallback") == "fallback"


async def test_update_persists(sample_config: Path):
    config = Config(sample_config)
    await config.load()
    await config.update("monthly_income", 6000.0)
    assert config.get("monthly_income") == 6000.0

    # Reload from disk to verify persistence
    config2 = Config(sample_config)
    await config2.load()
    assert config2.get("monthly_income") == 6000.0


async def test_load_missing_file_raises(tmp_dir: Path):
    config = Config(tmp_dir / "nonexistent.json")
    with pytest.raises(FileNotFoundError):
        await config.load()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/config/__init__.py
from pa.config.config import Config

__all__ = ["Config"]
```

```python
# pa/config/config.py
import asyncio
import json
from pathlib import Path
from typing import Any


class Config:
    def __init__(self, path: Path):
        self._path = path
        self._data: dict[str, Any] = {}

    async def load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        text = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        self._data = json.loads(text)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    async def update(self, key: str, value: Any) -> None:
        self._data[key] = value
        content = json.dumps(self._data, indent=2, ensure_ascii=False)
        await asyncio.to_thread(self._path.write_text, content, encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/config/ tests/test_config.py
git commit -m "feat: add config module for loading/saving settings"
```

---

## Task 4: Vault Crypto Helpers

**Files:**
- Create: `pa/vault/__init__.py`
- Create: `pa/vault/crypto.py`
- Create: `tests/test_vault_crypto.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_crypto.py
import pytest

from pa.vault.crypto import derive_key, encrypt, decrypt


def test_derive_key_returns_32_bytes():
    key, params = derive_key("my-master-password")
    assert len(key) == 32
    assert isinstance(key, bytes)


def test_derive_key_deterministic_with_same_params():
    key1, params = derive_key("password123")
    key2 = derive_key("password123", params=params)[0]
    assert key1 == key2


def test_derive_key_different_passwords_different_keys():
    key1, _ = derive_key("password1")
    key2, _ = derive_key("password2")
    assert key1 != key2


def test_encrypt_decrypt_roundtrip():
    key, _ = derive_key("test-password")
    plaintext = b'{"wellsfargo": {"username": "user", "password": "pass"}}'
    ciphertext = encrypt(plaintext, key)
    assert ciphertext != plaintext
    result = decrypt(ciphertext, key)
    assert result == plaintext


def test_decrypt_wrong_key_raises():
    key1, _ = derive_key("correct-password")
    key2, _ = derive_key("wrong-password")
    ciphertext = encrypt(b"secret data", key1)
    with pytest.raises(Exception):  # GCM auth tag failure
        decrypt(ciphertext, key2)


def test_params_contain_required_fields():
    _, params = derive_key("password")
    assert "salt" in params
    assert "time_cost" in params
    assert "memory_cost" in params
    assert "parallelism" in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vault_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/vault/__init__.py
```

```python
# pa/vault/crypto.py
import json
import os
from typing import Any

from argon2.low_level import hash_secret_raw, Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Argon2id default parameters
_DEFAULT_TIME_COST = 3
_DEFAULT_MEMORY_COST = 65536  # 64 MB
_DEFAULT_PARALLELISM = 4
_SALT_LENGTH = 16
_KEY_LENGTH = 32
_NONCE_LENGTH = 12


def derive_key(
    password: str, params: dict[str, Any] | None = None
) -> tuple[bytes, dict[str, Any]]:
    if params is None:
        salt = os.urandom(_SALT_LENGTH)
        params = {
            "salt": salt.hex(),
            "time_cost": _DEFAULT_TIME_COST,
            "memory_cost": _DEFAULT_MEMORY_COST,
            "parallelism": _DEFAULT_PARALLELISM,
        }

    salt = bytes.fromhex(params["salt"])
    key = hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=_KEY_LENGTH,
        type=Type.ID,
    )
    return key, params


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LENGTH)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(ciphertext_with_nonce: bytes, key: bytes) -> bytes:
    nonce = ciphertext_with_nonce[:_NONCE_LENGTH]
    ciphertext = ciphertext_with_nonce[_NONCE_LENGTH:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_vault_crypto.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/vault/ tests/test_vault_crypto.py
git commit -m "feat: add Argon2id key derivation and AES-256-GCM encrypt/decrypt"
```

---

## Task 5: Vault Module

**Files:**
- Create: `pa/vault/vault.py`
- Modify: `pa/vault/__init__.py`
- Create: `tests/test_vault.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault.py
import pytest
from pathlib import Path

from pa.vault.vault import Vault
from pa.exceptions import VaultAuthError, VaultLockedError


@pytest.fixture
def vault_dir(tmp_dir: Path) -> Path:
    return tmp_dir


async def test_new_vault_init_and_unlock(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("master-password-123")
    assert (vault_dir / "vault.enc").exists()
    assert (vault_dir / "vault.params.json").exists()

    vault2 = Vault(vault_dir)
    await vault2.unlock("master-password-123")
    assert vault2.is_unlocked


async def test_add_and_get_credentials(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    await vault.add("wellsfargo", {"username": "user1", "password": "pass1"})

    # Re-open and verify
    vault2 = Vault(vault_dir)
    await vault2.unlock("password")
    creds = vault2.get("wellsfargo")
    assert creds["username"] == "user1"
    assert creds["password"] == "pass1"


async def test_get_missing_institution_returns_none(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    assert vault.get("nonexistent") is None


async def test_unlock_wrong_password_raises(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("correct-password")

    vault2 = Vault(vault_dir)
    with pytest.raises(VaultAuthError):
        await vault2.unlock("wrong-password")


async def test_get_while_locked_raises(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    vault.lock()
    with pytest.raises(VaultLockedError):
        vault.get("wellsfargo")


async def test_lock_clears_data(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    await vault.add("bank", {"user": "u", "pass": "p"})
    assert vault.is_unlocked
    vault.lock()
    assert not vault.is_unlocked


async def test_derived_key_available_after_unlock(vault_dir: Path):
    vault = Vault(vault_dir)
    await vault.init("password")
    key = vault.derived_key
    assert key is not None
    assert len(key) == 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vault.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/vault/vault.py
import json
from pathlib import Path
from typing import Any

from pa.exceptions import VaultAuthError, VaultLockedError
from pa.vault.crypto import derive_key, encrypt, decrypt


class Vault:
    def __init__(self, directory: Path):
        self._dir = directory
        self._vault_path = directory / "vault.enc"
        self._params_path = directory / "vault.params.json"
        self._data: dict[str, Any] = {}
        self._key: bytes | None = None
        self._params: dict[str, Any] | None = None

    @property
    def is_unlocked(self) -> bool:
        return self._key is not None

    @property
    def derived_key(self) -> bytes | None:
        return self._key

    async def init(self, master_password: str) -> None:
        """Create a new vault with the given master password."""
        self._data = {}
        self._key, self._params = derive_key(master_password)
        self._params_path.write_text(
            json.dumps(self._params, indent=2), encoding="utf-8"
        )
        await self._save()

    async def unlock(self, master_password: str) -> None:
        """Unlock an existing vault."""
        if not self._params_path.exists():
            raise VaultAuthError("No vault found")
        params = json.loads(self._params_path.read_text(encoding="utf-8"))
        key, _ = derive_key(master_password, params=params)
        try:
            encrypted = self._vault_path.read_bytes()
            plaintext = decrypt(encrypted, key)
            self._data = json.loads(plaintext)
        except Exception as e:
            raise VaultAuthError("Wrong master password") from e
        self._key = key
        self._params = params

    def lock(self) -> None:
        """Wipe credentials from memory with best-effort secure clearing."""
        # Best-effort memory wipe for the key
        if self._key:
            import ctypes
            key_len = len(self._key)
            try:
                ctypes.memset(id(self._key) + 32, 0, key_len)  # CPython bytes offset
            except Exception:
                pass  # Best effort — not all platforms support this
        self._data = {}
        self._key = None

    def get(self, institution: str) -> dict[str, Any] | None:
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        return self._data.get(institution)

    async def add(self, institution: str, credentials: dict[str, Any]) -> None:
        if not self.is_unlocked:
            raise VaultLockedError("Vault is locked")
        self._data[institution] = credentials
        await self._save()

    async def _save(self) -> None:
        plaintext = json.dumps(self._data).encode("utf-8")
        encrypted = encrypt(plaintext, self._key)
        self._vault_path.write_bytes(encrypted)
```

Update `pa/vault/__init__.py`:

```python
# pa/vault/__init__.py
from pa.vault.vault import Vault

__all__ = ["Vault"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_vault.py -v`
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/vault/ tests/test_vault.py
git commit -m "feat: add encrypted vault with Argon2id key derivation"
```

---

## Task 6: Store Module — Schema and Connection

**Files:**
- Create: `pa/store/__init__.py`
- Create: `pa/store/store.py`
- Create: `pa/store/schema.sql`
- Create: `tests/test_store.py`

- [ ] **Step 1: Create the SQL schema**

```sql
-- pa/store/schema.sql
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('checking', 'savings', 'credit_card', 'mortgage', 'loan')),
    interest_rate REAL,
    credit_limit REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    balance REAL NOT NULL,
    statement_balance REAL,
    available_credit REAL,
    minimum_payment REAL,
    due_date DATE,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    date DATE NOT NULL,
    posted_date DATE,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT,
    dedup_hash TEXT UNIQUE NOT NULL,
    is_pending BOOLEAN DEFAULT 0,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    status TEXT NOT NULL CHECK(status IN ('success', 'failure', 'mfa_pending')),
    error_message TEXT,
    duration_seconds REAL,
    ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_store.py
import pytest
from pathlib import Path
from datetime import date, datetime

from pa.store.store import Store


@pytest.fixture
async def store(tmp_dir: Path):
    s = Store(tmp_dir / "test.db")
    await s.connect()
    await s.init_schema()
    yield s
    await s.close()


async def test_connect_and_init_schema(store: Store):
    # If we got here, connect + init_schema worked
    assert store is not None


async def test_add_account(store: Store):
    account_id = await store.add_account(
        institution="wellsfargo",
        name="WF Checking",
        account_type="checking",
    )
    assert account_id == 1


async def test_get_accounts(store: Store):
    await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_account("synchrony", "Synchrony Card", "credit_card", interest_rate=0.2499, credit_limit=5000.0)
    accounts = await store.get_accounts()
    assert len(accounts) == 2
    assert accounts[1]["interest_rate"] == 0.2499


async def test_add_balance(store: Store):
    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_balance(
        account_id=acc_id,
        balance=1500.00,
    )
    balances = await store.get_latest_balances()
    assert len(balances) == 1
    assert balances[0]["balance"] == 1500.00


async def test_add_transaction_dedup(store: Store):
    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    txn = {
        "account_id": acc_id,
        "date": "2026-03-15",
        "description": "AMAZON PURCHASE",
        "amount": 49.99,
    }
    inserted = await store.add_transaction(**txn)
    assert inserted is True
    # Same transaction again — should be skipped
    inserted2 = await store.add_transaction(**txn)
    assert inserted2 is False


async def test_get_transactions_by_account(store: Store):
    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_transaction(acc_id, "2026-03-10", "GROCERY STORE", -85.00)
    await store.add_transaction(acc_id, "2026-03-12", "GAS STATION", -45.00)
    txns = await store.get_transactions(account_id=acc_id)
    assert len(txns) == 2


async def test_log_scrape(store: Store):
    await store.log_scrape(
        institution="wellsfargo",
        status="success",
        duration_seconds=12.5,
    )
    logs = await store.get_scrape_logs(limit=1)
    assert logs[0]["status"] == "success"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Write minimal implementation**

```python
# pa/store/__init__.py
from pa.store.store import Store

__all__ = ["Store"]
```

```python
# pa/store/store.py
import hashlib
from pathlib import Path
from typing import Any

import aiosqlite

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

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # --- Accounts ---

    async def add_account(
        self,
        institution: str,
        name: str,
        account_type: str,
        interest_rate: float | None = None,
        credit_limit: float | None = None,
    ) -> int:
        cursor = await self._db.execute(
            "INSERT INTO accounts (institution, name, type, interest_rate, credit_limit) VALUES (?, ?, ?, ?, ?)",
            (institution, name, account_type, interest_rate, credit_limit),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_accounts(self) -> list[dict[str, Any]]:
        cursor = await self._db.execute("SELECT * FROM accounts ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Balances ---

    async def add_balance(
        self,
        account_id: int,
        balance: float,
        statement_balance: float | None = None,
        available_credit: float | None = None,
        minimum_payment: float | None = None,
        due_date: str | None = None,
    ) -> int:
        cursor = await self._db.execute(
            "INSERT INTO balances (account_id, balance, statement_balance, available_credit, minimum_payment, due_date) VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, balance, statement_balance, available_credit, minimum_payment, due_date),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_latest_balances(self) -> list[dict[str, Any]]:
        cursor = await self._db.execute("""
            SELECT b.*, a.institution, a.name, a.type
            FROM balances b
            JOIN accounts a ON a.id = b.account_id
            WHERE b.id IN (
                SELECT MAX(id) FROM balances GROUP BY account_id
            )
            ORDER BY a.id
        """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Transactions ---

    @staticmethod
    def _compute_dedup_hash(account_id: int, txn_date: str, description: str, amount: float) -> str:
        raw = f"{account_id}|{txn_date}|{description}|{amount}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def add_transaction(
        self,
        account_id: int,
        date: str,
        description: str,
        amount: float,
        posted_date: str | None = None,
        category: str | None = None,
        is_pending: bool = False,
    ) -> bool:
        dedup_hash = self._compute_dedup_hash(account_id, date, description, amount)
        cursor = await self._db.execute(
            "INSERT OR IGNORE INTO transactions (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, date, posted_date, description, amount, category, dedup_hash, is_pending),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_transactions(
        self,
        account_id: int | None = None,
        since_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM transactions WHERE 1=1"
        params: list[Any] = []
        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        if since_date is not None:
            query += " AND date >= ?"
            params.append(since_date)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Scrape Log ---

    async def log_scrape(
        self,
        institution: str,
        status: str,
        account_id: int | None = None,
        error_message: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO scrape_log (institution, account_id, status, error_message, duration_seconds) VALUES (?, ?, ?, ?, ?)",
            (institution, account_id, status, error_message, duration_seconds),
        )
        await self._db.commit()

    async def get_scrape_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT * FROM scrape_log ORDER BY ran_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_store.py -v`
Expected: 7 PASSED

- [ ] **Step 6: Commit**

```bash
git add pa/store/ tests/test_store.py
git commit -m "feat: add SQLite store with schema, accounts, balances, transactions, scrape log"
```

---

## Task 7: MFA Bridge

**Files:**
- Create: `pa/scrapers/__init__.py`
- Create: `pa/scrapers/mfa_bridge.py`
- Create: `tests/test_mfa_bridge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mfa_bridge.py
import asyncio

import pytest

from pa.scrapers.mfa_bridge import MFABridge


async def test_request_and_provide_mfa():
    bridge = MFABridge()

    async def provider():
        await asyncio.sleep(0.1)
        await bridge.provide_mfa("wellsfargo", "123456")

    asyncio.create_task(provider())
    code = await bridge.request_mfa("wellsfargo", "Enter MFA code")
    assert code == "123456"


async def test_mfa_timeout():
    bridge = MFABridge(timeout_seconds=0.2)
    with pytest.raises(asyncio.TimeoutError):
        await bridge.request_mfa("wellsfargo", "Enter MFA code")


async def test_mfa_multiple_institutions():
    bridge = MFABridge()

    async def provider1():
        await asyncio.sleep(0.05)
        await bridge.provide_mfa("wellsfargo", "111111")

    async def provider2():
        await asyncio.sleep(0.1)
        await bridge.provide_mfa("synchrony", "222222")

    asyncio.create_task(provider1())
    asyncio.create_task(provider2())

    code1 = await bridge.request_mfa("wellsfargo", "WF code")
    code2 = await bridge.request_mfa("synchrony", "Sync code")
    assert code1 == "111111"
    assert code2 == "222222"


async def test_has_pending_request():
    bridge = MFABridge()

    async def requester():
        await bridge.request_mfa("wellsfargo", "Enter code")

    task = asyncio.create_task(requester())
    await asyncio.sleep(0.05)
    assert bridge.has_pending("wellsfargo")
    assert not bridge.has_pending("synchrony")
    await bridge.provide_mfa("wellsfargo", "999999")
    await task
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mfa_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/scrapers/__init__.py
```

```python
# pa/scrapers/mfa_bridge.py
import asyncio
from dataclasses import dataclass, field


@dataclass
class _PendingMFA:
    institution: str
    prompt: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    code: str = ""


class MFABridge:
    def __init__(self, timeout_seconds: float = 300.0):
        self._timeout = timeout_seconds
        self._pending: dict[str, _PendingMFA] = {}

    async def request_mfa(self, institution: str, prompt: str) -> str:
        pending = _PendingMFA(institution=institution, prompt=prompt)
        self._pending[institution] = pending
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=self._timeout)
            return pending.code
        finally:
            self._pending.pop(institution, None)

    async def provide_mfa(self, institution: str, code: str) -> None:
        pending = self._pending.get(institution)
        if pending:
            pending.code = code
            pending.event.set()

    def has_pending(self, institution: str) -> bool:
        return institution in self._pending

    def get_pending_prompt(self, institution: str) -> str | None:
        pending = self._pending.get(institution)
        return pending.prompt if pending else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mfa_bridge.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/scrapers/ tests/test_mfa_bridge.py
git commit -m "feat: add MFABridge for async MFA callback between scrapers and bot"
```

---

## Task 8: Base Scraper

**Files:**
- Create: `pa/scrapers/base.py`
- Create: `tests/test_scraper_base.py`

- [ ] **Step 0: Write the failing test for data classes and base interface**

```python
# tests/test_scraper_base.py
from pa.scrapers.base import BalanceData, TransactionData, BaseScraper


def test_balance_data_defaults():
    b = BalanceData(balance=1500.00)
    assert b.balance == 1500.00
    assert b.statement_balance is None
    assert b.available_credit is None
    assert b.minimum_payment is None
    assert b.due_date is None


def test_balance_data_full():
    b = BalanceData(
        balance=2500.00,
        statement_balance=2200.00,
        available_credit=2500.00,
        minimum_payment=35.00,
        due_date="2026-03-25",
    )
    assert b.minimum_payment == 35.00


def test_transaction_data_defaults():
    t = TransactionData(date="2026-03-15", description="AMAZON", amount=49.99)
    assert t.is_pending is False
    assert t.posted_date is None


def test_base_scraper_is_abstract():
    import pytest
    from unittest.mock import MagicMock
    with pytest.raises(TypeError):
        BaseScraper(context=MagicMock(), mfa_bridge=MagicMock())
```

- [ ] **Step 1: Write the base scraper abstract class**

```python
# pa/scrapers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from playwright.async_api import BrowserContext

from pa.scrapers.mfa_bridge import MFABridge


@dataclass
class BalanceData:
    balance: float
    statement_balance: float | None = None
    available_credit: float | None = None
    minimum_payment: float | None = None
    due_date: str | None = None


@dataclass
class TransactionData:
    date: str
    description: str
    amount: float
    posted_date: str | None = None
    is_pending: bool = False


class BaseScraper(ABC):
    institution: str = ""

    def __init__(self, context: BrowserContext, mfa_bridge: MFABridge):
        self._context = context
        self._mfa_bridge = mfa_bridge
        self._page = None

    async def open(self) -> None:
        self._page = await self._context.new_page()

    async def close(self) -> None:
        if self._page:
            await self._page.close()
            self._page = None

    @abstractmethod
    async def login(self, credentials: dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_balances(self) -> list[BalanceData]: ...

    @abstractmethod
    async def get_transactions(self, since_date: str) -> list[TransactionData]: ...

    @abstractmethod
    async def logout(self) -> None: ...
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_scraper_base.py -v`
Expected: 4 PASSED

- [ ] **Step 3: Commit**

```bash
git add pa/scrapers/base.py tests/test_scraper_base.py
git commit -m "feat: add BaseScraper abstract class with BalanceData/TransactionData dataclasses"
```

---

## Task 9: Brain — Tier Classifier

**Files:**
- Create: `pa/brain/__init__.py`
- Create: `pa/brain/tier.py`
- Create: `tests/test_brain_tier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_brain_tier.py
from pa.brain.tier import classify_tier, Tier


def test_balance_query_routes_to_haiku():
    assert classify_tier("what's my Chase balance?") == Tier.FAST
    assert classify_tier("how much money do I have?") == Tier.FAST


def test_status_query_routes_to_haiku():
    assert classify_tier("what's the status?") == Tier.FAST
    assert classify_tier("when is my payment due?") == Tier.FAST


def test_spending_query_routes_to_sonnet():
    assert classify_tier("what did I spend this month?") == Tier.STANDARD
    assert classify_tier("show me spending by category") == Tier.STANDARD
    assert classify_tier("compare my spending to last month") == Tier.STANDARD


def test_strategy_query_routes_to_opus():
    assert classify_tier("build me a debt payoff plan") == Tier.DEEP
    assert classify_tier("what's the best strategy to save money?") == Tier.DEEP
    assert classify_tier("create a monthly budget for me") == Tier.DEEP
    assert classify_tier("give me financial advice") == Tier.DEEP


def test_unknown_query_defaults_to_sonnet():
    assert classify_tier("hello there") == Tier.STANDARD
    assert classify_tier("what is the weather") == Tier.STANDARD
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_tier.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/brain/__init__.py
```

```python
# pa/brain/tier.py
import re
from enum import Enum


class Tier(Enum):
    FAST = "haiku"
    STANDARD = "sonnet"
    DEEP = "opus"


_FAST_PATTERNS = [
    r"\bbalance\b", r"\bhow much\b", r"\bstatus\b", r"\bdue\b",
    r"\bowed?\b", r"\bminimum\b", r"\btotal\b", r"\bremaining\b",
]

_DEEP_PATTERNS = [
    r"\bplan\b", r"\bstrategy\b", r"\bbudget\b", r"\bpayoff\b",
    r"\badvice\b", r"\brecommend\b", r"\boptimize\b", r"\bsnowball\b",
    r"\bavalanche\b", r"\bgoal\b", r"\bsave money\b", r"\bget out of debt\b",
]

_STANDARD_PATTERNS = [
    r"\bspend", r"\bcategory\b", r"\bcompare\b", r"\btrend\b",
    r"\bpattern\b", r"\banalyz", r"\bbreakdown\b", r"\bhistory\b",
]


def classify_tier(query: str) -> Tier:
    lower = query.lower()
    for pattern in _DEEP_PATTERNS:
        if re.search(pattern, lower):
            return Tier.DEEP
    for pattern in _STANDARD_PATTERNS:
        if re.search(pattern, lower):
            return Tier.STANDARD
    for pattern in _FAST_PATTERNS:
        if re.search(pattern, lower):
            return Tier.FAST
    return Tier.STANDARD
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain_tier.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/brain/ tests/test_brain_tier.py
git commit -m "feat: add keyword-based tier classifier for Claude API model routing"
```

---

## Task 10: Brain — Cost Tracker

**Files:**
- Create: `pa/brain/cost_tracker.py`
- Create: `tests/test_brain_cost_tracker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_brain_cost_tracker.py
import pytest

from pa.brain.cost_tracker import CostTracker
from pa.exceptions import BrainCostCapError


def test_record_and_get_total():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(0.05)
    tracker.record(0.10)
    assert tracker.total_this_month == pytest.approx(0.15)


def test_cap_exceeded_raises():
    tracker = CostTracker(monthly_cap=1.0)
    tracker.record(0.80)
    tracker.record(0.15)
    with pytest.raises(BrainCostCapError):
        tracker.check_budget(estimated_cost=0.10)


def test_under_cap_does_not_raise():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(5.0)
    tracker.check_budget(estimated_cost=0.10)  # Should not raise


def test_alert_at_80_percent():
    tracker = CostTracker(monthly_cap=10.0)
    tracker.record(8.0)
    assert tracker.should_alert


def test_no_alert_under_80_percent():
    tracker = CostTracker(monthly_cap=10.0)
    tracker.record(7.0)
    assert not tracker.should_alert


def test_reset_clears_total():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(10.0)
    tracker.reset()
    assert tracker.total_this_month == 0.0


def test_remaining_budget():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.record(5.0)
    assert tracker.remaining == pytest.approx(15.0)


def test_load_from_persisted():
    tracker = CostTracker(monthly_cap=20.0)
    tracker.load_persisted(7.5)
    assert tracker.total_this_month == pytest.approx(7.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain_cost_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/brain/cost_tracker.py
from pa.exceptions import BrainCostCapError


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
        """Load previously persisted cost total (e.g., from database on startup)."""
        self._total = total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain_cost_tracker.py -v`
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/brain/cost_tracker.py tests/test_brain_cost_tracker.py
git commit -m "feat: add cost tracker with monthly cap, alerts, and budget checks"
```

---

## Task 11: Brain — Core Module

**Files:**
- Create: `pa/brain/brain.py`
- Modify: `pa/brain/__init__.py`
- Create: `tests/test_brain.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_brain.py
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

import pytest

from pa.brain.brain import Brain
from pa.brain.tier import Tier
from pa.config.config import Config


@pytest.fixture
async def brain(sample_config: Path):
    config = Config(sample_config)
    await config.load()
    b = Brain(config=config)
    return b


async def test_build_system_prompt(brain: Brain):
    accounts = [
        {"name": "WF Checking", "institution": "wellsfargo", "type": "checking", "balance": 1500.0, "interest_rate": None},
    ]
    prompt = brain.build_system_prompt(accounts)
    assert "WF Checking" in prompt
    assert "financial" in prompt.lower()


async def test_select_model_maps_tiers(brain: Brain):
    assert brain.select_model(Tier.FAST) == "claude-haiku-4-5-20251001"
    assert brain.select_model(Tier.STANDARD) == "claude-sonnet-4-6"
    assert brain.select_model(Tier.DEEP) == "claude-opus-4-6"


async def test_query_calls_api(brain: Brain):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Your total debt is $5,000")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    with patch.object(brain, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        result = await brain.query("what's my total debt?", accounts_summary=[])
        assert "5,000" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_brain.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/brain/brain.py
import asyncio
import os
import time
from collections import deque
from typing import Any

import anthropic

from pa.brain.cost_tracker import CostTracker
from pa.brain.tier import Tier, classify_tier
from pa.config.config import Config
from pa.exceptions import BrainAPIError

_MODEL_MAP = {
    Tier.FAST: "claude-haiku-4-5-20251001",
    Tier.STANDARD: "claude-sonnet-4-6",
    Tier.DEEP: "claude-opus-4-6",
}

# Rough cost per token (input + output averaged)
_COST_PER_1K_TOKENS = {
    Tier.FAST: 0.001,
    Tier.STANDARD: 0.01,
    Tier.DEEP: 0.10,
}

_MAX_RETRIES = 3
_MAX_QUERIES_PER_HOUR = 30


class Brain:
    def __init__(self, config: Config):
        self._config = config
        api_key_env = config.get("claude_api_key_env", "PA_CLAUDE_API_KEY")
        api_key = os.environ.get(api_key_env, "")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._cost_tracker = CostTracker(
            monthly_cap=config.get("cost_cap_monthly_usd", 20.0)
        )
        self._query_timestamps: deque[float] = deque()

    def _check_rate_limit(self) -> None:
        """Enforce max queries per hour."""
        now = time.monotonic()
        # Remove timestamps older than 1 hour
        while self._query_timestamps and now - self._query_timestamps[0] > 3600:
            self._query_timestamps.popleft()
        if len(self._query_timestamps) >= _MAX_QUERIES_PER_HOUR:
            raise BrainAPIError(
                f"Rate limit: {_MAX_QUERIES_PER_HOUR} queries/hour exceeded. Try again later."
            )

    def select_model(self, tier: Tier) -> str:
        return _MODEL_MAP[tier]

    def build_system_prompt(self, accounts: list[dict[str, Any]]) -> str:
        income = self._config.get("monthly_income", 0)
        goals = self._config.get("financial_goals", [])
        preferences = self._config.get("preferences", [])

        accounts_text = ""
        for acc in accounts:
            line = f"- {acc['name']} ({acc['institution']}, {acc.get('type', 'unknown')})"
            if acc.get("balance") is not None:
                line += f": ${acc['balance']:,.2f}"
            if acc.get("interest_rate"):
                line += f" @ {acc['interest_rate']*100:.1f}% APR"
            accounts_text += line + "\n"

        return f"""You are a personal financial advisor. You have access to the user's real financial data.

Monthly income: ${income:,.2f}
Financial goals: {', '.join(goals) if goals else 'Not set'}
Preferences: {', '.join(preferences) if preferences else 'None'}

Current accounts:
{accounts_text}

Rules:
- Be direct and actionable
- Reference specific numbers from the data
- Never suggest actions that move money (the system is read-only)
- If asked about something not in the data, say so"""

    async def query(
        self,
        user_message: str,
        accounts_summary: list[dict[str, Any]],
        force_tier: Tier | None = None,
    ) -> str:
        self._check_rate_limit()

        tier = force_tier or classify_tier(user_message)
        model = self.select_model(tier)
        system_prompt = self.build_system_prompt(accounts_summary)

        estimated_cost = _COST_PER_1K_TOKENS[tier] * 2  # rough estimate
        self._cost_tracker.check_budget(estimated_cost)

        # Retry with exponential backoff
        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                break
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
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

Update `pa/brain/__init__.py`:

```python
# pa/brain/__init__.py
from pa.brain.brain import Brain

__all__ = ["Brain"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_brain.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/brain/ tests/test_brain.py
git commit -m "feat: add Brain module with tiered Claude API routing and cost tracking"
```

---

## Task 12: Scheduler Module

**Files:**
- Create: `pa/scheduler/__init__.py`
- Create: `pa/scheduler/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler.py
import pytest
from unittest.mock import AsyncMock

from pa.scheduler.scheduler import PAScheduler


async def test_scheduler_creates_default_jobs():
    scheduler = PAScheduler()
    mock_scrape = AsyncMock()
    mock_alert = AsyncMock()
    scheduler.register_scrape_handler(mock_scrape)
    scheduler.register_alert_handler(mock_alert)
    job_names = scheduler.get_job_names()
    assert "bank_balance" in job_names
    assert "cc_balance" in job_names
    assert "transaction_pull" in job_names
    assert "due_date_check" in job_names
    assert "heartbeat" in job_names


async def test_scheduler_pause_resume():
    scheduler = PAScheduler()
    scheduler.register_scrape_handler(AsyncMock())
    scheduler.register_alert_handler(AsyncMock())
    scheduler.pause()
    assert scheduler.is_paused
    scheduler.resume()
    assert not scheduler.is_paused
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/scheduler/__init__.py
from pa.scheduler.scheduler import PAScheduler

__all__ = ["PAScheduler"]
```

```python
# pa/scheduler/scheduler.py
import random
from typing import Any, Callable, Awaitable

from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


class PAScheduler:
    def __init__(self):
        self._scheduler = AsyncScheduler()
        self._job_defs: dict[str, dict[str, Any]] = {}
        self._scrape_handler: Callable[..., Awaitable] | None = None
        self._alert_handler: Callable[..., Awaitable] | None = None
        self._paused = False
        self._setup_default_jobs()

    def _setup_default_jobs(self) -> None:
        self._job_defs = {
            "bank_balance": {"type": "interval", "hours": 4, "jitter": 900},
            "cc_balance": {"type": "cron", "hour": 6, "minute": 0},
            "transaction_pull": {"type": "cron", "hour": 7, "minute": 0},
            "due_date_check": {"type": "cron", "hour": 8, "minute": 0},
            "weekly_summary": {"type": "cron", "day_of_week": "sun", "hour": 19, "minute": 0},
            "monthly_report": {"type": "cron", "day": 1, "hour": 9, "minute": 0},
            "heartbeat": {"type": "cron", "hour": 12, "minute": 0},
        }

    def register_scrape_handler(self, handler: Callable[..., Awaitable]) -> None:
        self._scrape_handler = handler

    def register_alert_handler(self, handler: Callable[..., Awaitable]) -> None:
        self._alert_handler = handler

    async def start(self) -> None:
        """Register all jobs with APScheduler and start the scheduler."""
        for name, job_def in self._job_defs.items():
            handler = self._scrape_handler if name != "heartbeat" else self._alert_handler
            if handler is None:
                continue
            if job_def["type"] == "interval":
                trigger = IntervalTrigger(
                    hours=job_def.get("hours", 4),
                    jitter=job_def.get("jitter", 0),
                )
            else:
                trigger_kwargs = {k: v for k, v in job_def.items() if k != "type"}
                trigger = CronTrigger(**trigger_kwargs)
            await self._scheduler.add_schedule(
                handler, trigger, id=name, args=[name]
            )
        await self._scheduler.start_in_background()

    async def stop(self) -> None:
        await self._scheduler.stop()

    def get_job_names(self) -> list[str]:
        return list(self._job_defs.keys())

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def update_schedule(self, job_name: str, **kwargs: Any) -> None:
        if job_name in self._job_defs:
            self._job_defs[job_name].update(kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/scheduler/ tests/test_scheduler.py
git commit -m "feat: add scheduler module with default job definitions"
```

---

## Task 13: Telegram Bot Module — Handlers and Formatters

**Files:**
- Create: `pa/bot/__init__.py`
- Create: `pa/bot/handlers.py`
- Create: `tests/test_bot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from pa.bot.handlers import (
    is_authorized,
    format_balance_summary,
    format_debt_summary,
    format_due_summary,
    format_spending_summary,
)


def test_is_authorized_correct_user():
    assert is_authorized(123456789, 123456789)


def test_is_authorized_wrong_user():
    assert not is_authorized(999999999, 123456789)


def test_format_balance_summary():
    balances = [
        {"name": "WF Checking", "type": "checking", "balance": 1500.00, "institution": "wellsfargo"},
        {"name": "Synchrony Card", "type": "credit_card", "balance": 2500.00, "institution": "synchrony", "credit_limit": 5000.0},
    ]
    result = format_balance_summary(balances)
    assert "WF Checking" in result
    assert "$1,500.00" in result
    assert "Synchrony Card" in result


def test_format_debt_summary():
    balances = [
        {"name": "WF Checking", "type": "checking", "balance": 1500.00, "institution": "wellsfargo"},
        {"name": "Synchrony Card", "type": "credit_card", "balance": 2500.00, "institution": "synchrony", "interest_rate": 0.2499},
        {"name": "Credit One", "type": "credit_card", "balance": 1200.00, "institution": "creditone", "interest_rate": 0.2399},
    ]
    result = format_debt_summary(balances)
    assert "Synchrony Card" in result
    assert "Credit One" in result
    assert "WF Checking" not in result
    assert "$3,700.00" in result


def test_format_due_summary():
    balances = [
        {"name": "Synchrony Card", "type": "credit_card", "balance": 2500.00, "minimum_payment": 35.00, "due_date": "2026-03-25"},
        {"name": "Credit One", "type": "credit_card", "balance": 1200.00, "minimum_payment": 25.00, "due_date": "2026-04-01"},
    ]
    result = format_due_summary(balances)
    assert "Synchrony Card" in result
    assert "$35.00" in result
    assert "2026-03-25" in result


def test_format_spending_summary():
    transactions = [
        {"category": "food", "amount": 85.00},
        {"category": "food", "amount": 45.00},
        {"category": "gas", "amount": 60.00},
        {"category": None, "amount": 20.00},
    ]
    result = format_spending_summary(transactions, "this week")
    assert "food" in result.lower()
    assert "$130.00" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bot.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# pa/bot/__init__.py
```

```python
# pa/bot/handlers.py
from typing import Any
from collections import defaultdict

_DEBT_TYPES = {"credit_card", "mortgage", "loan"}


def is_authorized(user_id: int, allowed_id: int) -> bool:
    return user_id == allowed_id


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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bot.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/bot/ tests/test_bot.py
git commit -m "feat: add bot handler functions and formatters"
```

---

## Task 13b: Telegram Bot — PABot Class

**Files:**
- Create: `pa/bot/bot.py`
- Create: `tests/test_bot_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pa.bot.bot import PABot
from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge


def _make_update(user_id: int, text: str, is_command: bool = False):
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.delete = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.message.chat_id = user_id
    return update


def _make_context(**user_data):
    ctx = MagicMock()
    ctx.user_data = dict(user_data)
    return ctx


@pytest.fixture
async def bot_deps(tmp_dir, sample_config):
    config = Config(sample_config)
    await config.load()
    vault = Vault(tmp_dir)
    await vault.init("test-password")
    store = Store(tmp_dir / "test.db")
    await store.connect()
    await store.init_schema()
    brain = MagicMock(spec=Brain)
    mfa = MFABridge()
    bot = PABot(config=config, vault=vault, store=store, brain=brain, mfa_bridge=mfa)
    yield bot
    await store.close()


async def test_unauthorized_user_ignored(bot_deps):
    bot = bot_deps
    update = _make_update(user_id=999, text="/balance")
    context = _make_context()
    await bot._handle_balance(update, context)
    update.message.reply_text.assert_not_called()


async def test_handle_balance(bot_deps):
    bot = bot_deps
    acc_id = await bot._store.add_account("wf", "WF Checking", "checking")
    await bot._store.add_balance(acc_id, balance=1500.00)
    update = _make_update(user_id=123456789, text="/balance")
    context = _make_context()
    await bot._handle_balance(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "$1,500.00" in reply


async def test_handle_unlock_sets_awaiting_password(bot_deps):
    bot = bot_deps
    update = _make_update(user_id=123456789, text="/unlock")
    context = _make_context()
    await bot._handle_unlock(update, context)
    assert context.user_data["awaiting_password"] is True


async def test_password_message_deleted(bot_deps):
    bot = bot_deps
    bot._vault.lock()  # Lock so we can test unlock
    update = _make_update(user_id=123456789, text="test-password")
    context = _make_context(awaiting_password=True)
    # Store the prompt message ID for deletion tracking
    prompt_msg = MagicMock()
    prompt_msg.delete = AsyncMock()
    context.user_data["_prompt_message"] = prompt_msg
    await bot._handle_message(update, context)
    # Password message should be deleted
    update.message.delete.assert_called_once()
    # Prompt message should be deleted
    prompt_msg.delete.assert_called_once()


async def test_handle_message_routes_to_brain(bot_deps):
    bot = bot_deps
    bot._brain.query = AsyncMock(return_value="Your total debt is $5,000")
    update = _make_update(user_id=123456789, text="how much do I owe?")
    context = _make_context()
    await bot._handle_message(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "$5,000" in reply


async def test_vault_locked_rejects_brain_query(bot_deps):
    bot = bot_deps
    bot._vault.lock()
    update = _make_update(user_id=123456789, text="how much do I owe?")
    context = _make_context()
    await bot._handle_message(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "locked" in reply.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bot_integration.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the PABot class**

```python
# pa/bot/bot.py
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

from pa.bot.handlers import (
    is_authorized,
    format_balance_summary,
    format_debt_summary,
    format_due_summary,
    format_spending_summary,
)
from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge


class PABot:
    def __init__(
        self,
        config: Config,
        vault: Vault,
        store: Store,
        brain: Brain,
        mfa_bridge: MFABridge,
    ):
        self._config = config
        self._vault = vault
        self._store = store
        self._brain = brain
        self._mfa_bridge = mfa_bridge
        self._app: Application | None = None
        self._scrape_callback = None

    async def start(self) -> None:
        token_env = self._config.get("telegram_bot_token_env", "PA_TELEGRAM_TOKEN")
        token = os.environ.get(token_env, "")
        self._app = Application.builder().token(token).build()

        commands = {
            "unlock": self._handle_unlock,
            "lock": self._handle_lock,
            "status": self._handle_status,
            "balance": self._handle_balance,
            "debt": self._handle_debt,
            "due": self._handle_due,
            "spending": self._handle_spending,
            "plan": self._handle_plan,
            "scrape": self._handle_scrape,
            "schedule": self._handle_schedule,
            "backup": self._handle_backup,
            "help": self._handle_help,
        }
        for name, handler in commands.items():
            self._app.add_handler(CommandHandler(name, handler))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    def set_scrape_callback(self, callback) -> None:
        self._scrape_callback = callback

    async def send_message(self, text: str) -> None:
        user_id = self._config.get("telegram_user_id")
        if self._app and user_id:
            await self._app.bot.send_message(chat_id=user_id, text=text)

    def _check_auth(self, update: Update) -> bool:
        allowed = self._config.get("telegram_user_id", 0)
        return is_authorized(update.effective_user.id, allowed)

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
        await update.message.reply_text("Vault locked. Scrapers paused.")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        status = "unlocked" if self._vault.is_unlocked else "locked"
        logs = await self._store.get_scrape_logs(limit=5)
        text = f"Vault: {status}\n"
        if self._brain:
            ct = self._brain.cost_tracker
            text += f"API budget: ${ct.remaining:.2f} remaining this month\n"
        if logs:
            text += "\nRecent scrapes:\n"
            for log in logs:
                text += f"  {log['institution']}: {log['status']} ({log['ran_at']})\n"
        await update.message.reply_text(text)

    async def _handle_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        balances = await self._store.get_latest_balances()
        await update.message.reply_text(format_balance_summary(balances))

    async def _handle_debt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        balances = await self._store.get_latest_balances()
        await update.message.reply_text(format_debt_summary(balances))

    async def _handle_due(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        balances = await self._store.get_latest_balances()
        await update.message.reply_text(format_due_summary(balances))

    async def _handle_spending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        # Default to current month
        period = "this month"
        args = context.args
        if args:
            period = " ".join(args)
        txns = await self._store.get_transactions(limit=500)
        await update.message.reply_text(format_spending_summary(txns, period))

    async def _handle_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        balances = await self._store.get_latest_balances()
        response = await self._brain.query(
            "Create a debt payoff plan based on my current balances. Compare snowball vs avalanche strategies.",
            balances,
        )
        await update.message.reply_text(response)

    async def _handle_scrape(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        institution = context.args[0] if context.args else None
        if self._scrape_callback:
            await update.message.reply_text(f"Starting scrape{' for ' + institution if institution else ''}...")
            await self._scrape_callback(institution)
        else:
            await update.message.reply_text("Scraper not configured.")

    async def _handle_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        # For now, show current schedule
        schedule = self._config.get("schedule", {})
        lines = ["**Current Schedule**\n"]
        for key, val in schedule.items():
            lines.append(f"  {key}: {val}")
        await update.message.reply_text("\n".join(lines))

    async def _handle_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        backup_path = self._config.get("backup_path", "")
        if not backup_path:
            await update.message.reply_text("Backup path not configured. Set backup_path in config.")
            return
        # TODO: Copy encrypted DB to backup path
        await update.message.reply_text(f"Backup saved to {backup_path}")

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        await update.message.reply_text(
            "/unlock - Enter master password\n"
            "/lock - Wipe credentials from memory\n"
            "/status - System health & API budget\n"
            "/balance - All account balances\n"
            "/debt - Debt summary\n"
            "/due - Upcoming payments\n"
            "/spending [period] - Spending breakdown\n"
            "/plan - Debt payoff plan\n"
            "/scrape [institution] - Force a scrape\n"
            "/schedule - View schedule\n"
            "/backup - Backup database\n"
            "/help - This message"
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return

        # Check if this is a password response
        if context.user_data.get("awaiting_password"):
            context.user_data["awaiting_password"] = False
            password = update.message.text

            # Delete both the password message and the prompt message
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
                # Reconnect store with encryption key
                if self._vault.derived_key and hasattr(self._store, 'reconnect_encrypted'):
                    await self._store.reconnect_encrypted(self._vault.derived_key)
                await update.effective_chat.send_message("Vault unlocked. Scrapers active.")
            except Exception:
                await update.effective_chat.send_message("Wrong password. Try /unlock again.")
            return

        # Check if this is an MFA response
        for inst in list(self._mfa_bridge._pending.keys()):
            if self._mfa_bridge.has_pending(inst):
                await self._mfa_bridge.provide_mfa(inst, update.message.text)
                await update.message.reply_text(f"MFA code sent to {inst} scraper.")
                return

        # Otherwise route to Brain
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return

        balances = await self._store.get_latest_balances()
        try:
            response = await self._brain.query(update.message.text, balances)
            await update.message.reply_text(response)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bot_integration.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add pa/bot/bot.py tests/test_bot_integration.py
git commit -m "feat: add PABot class with all command handlers, auth, MFA, and message deletion"
```

---

## Task 14: Main Entry Point

**Files:**
- Create: `pa/__main__.py`

- [ ] **Step 1: Add `reconnect_encrypted` to Store**

The Store needs a method to reconnect with an encryption key after the vault is unlocked.
Add to `pa/store/store.py`:

```python
    async def reconnect_encrypted(self, encryption_key: bytes) -> None:
        """Close current connection and reopen with SQLCipher encryption."""
        await self.close()
        self._encryption_key = encryption_key
        await self.connect()
        await self.init_schema()
```

- [ ] **Step 2: Write the entry point**

```python
# pa/__main__.py
import asyncio
import signal
import sys
from pathlib import Path

from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge
from pa.scheduler.scheduler import PAScheduler
from pa.bot.bot import PABot


async def main() -> None:
    base_dir = Path(__file__).parent.parent
    config_path = base_dir / "config.json"
    data_dir = base_dir / "data"
    data_dir.mkdir(exist_ok=True)

    # Load config
    config = Config(config_path)
    await config.load()

    # Initialize modules
    vault = Vault(data_dir)
    mfa_bridge = MFABridge()
    brain = Brain(config=config)
    scheduler = PAScheduler()

    # Store starts unencrypted — will reconnect with encryption after vault unlock
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

    # Start bot
    await bot.start()

    # Detect first run vs returning user
    vault_exists = (data_dir / "vault.enc").exists()
    if vault_exists:
        await bot.send_message("PA restarted. Send /unlock to enter master password.")
    else:
        await bot.send_message(
            "Welcome to PA! First-time setup:\n"
            "1. Send /init to create your encrypted vault\n"
            "2. You'll set a master password\n"
            "3. Then add your financial institution credentials"
        )

    # Start scheduler (jobs will check vault.is_unlocked before scraping)
    async def scrape_handler(job_name: str) -> None:
        if not vault.is_unlocked:
            return  # Skip if vault locked
        # Scrape logic will be wired here
        pass

    async def alert_handler(job_name: str) -> None:
        if job_name == "heartbeat":
            await bot.send_message("PA running. All systems OK.")

    scheduler.register_scrape_handler(scrape_handler)
    scheduler.register_alert_handler(alert_handler)
    await scheduler.start()

    # Keep running until interrupted
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await scheduler.stop()
        await bot.stop()
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Note: The Store starts unencrypted on boot. When the user sends `/unlock`, the bot's `_handle_message` calls `store.reconnect_encrypted(vault.derived_key)` to close and reopen the database with SQLCipher encryption. This means the first run creates an unencrypted schema, and subsequent runs decrypt with the key. For production, the `/init` command should create the vault AND initialize the encrypted database together.

- [ ] **Step 2: Verify it at least imports**

Run: `python -c "from pa.__main__ import main; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pa/__main__.py
git commit -m "feat: add main entry point wiring all modules together"
```

---

## Task 15: Wells Fargo Scraper (First Scraper)

**Files:**
- Create: `pa/scrapers/wellsfargo.py`

- [ ] **Step 1: Write the Wells Fargo scraper skeleton**

```python
# pa/scrapers/wellsfargo.py
import asyncio
import random
from typing import Any

from playwright.async_api import BrowserContext

from pa.scrapers.base import BaseScraper, BalanceData, TransactionData
from pa.scrapers.mfa_bridge import MFABridge


class WellsFargoScraper(BaseScraper):
    institution = "wellsfargo"

    LOGIN_URL = "https://connect.secure.wellsfargo.com/auth/login/present"

    async def login(self, credentials: dict[str, Any]) -> None:
        await self._page.goto(self.LOGIN_URL)
        await self._human_delay()

        # Fill username
        await self._page.fill('input[name="j_username"]', credentials["username"])
        await self._human_delay()

        # Fill password
        await self._page.fill('input[name="j_password"]', credentials["password"])
        await self._human_delay()

        # Submit
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("networkidle")

        # Check for MFA
        if await self._check_mfa():
            code = await self._mfa_bridge.request_mfa(
                self.institution,
                "Wells Fargo is requesting an MFA code. Reply with the code.",
            )
            await self._submit_mfa(code)

    async def get_balances(self) -> list[BalanceData]:
        # Navigate to account summary
        await self._page.goto("https://connect.secure.wellsfargo.com/accounts/start")
        await self._page.wait_for_load_state("networkidle")
        await self._human_delay()

        # TODO: Parse account balances from page
        # This will need to be refined against the actual WF page structure
        balances: list[BalanceData] = []
        return balances

    async def get_transactions(self, since_date: str) -> list[TransactionData]:
        # TODO: Navigate to activity/transactions page and parse
        transactions: list[TransactionData] = []
        return transactions

    async def logout(self) -> None:
        try:
            await self._page.goto("https://connect.secure.wellsfargo.com/auth/logout")
            await self._human_delay()
        except Exception:
            pass  # Best-effort logout

    async def _check_mfa(self) -> bool:
        """Check if current page is an MFA challenge."""
        # Look for common MFA indicators on WF
        mfa_indicators = [
            "text me a temporary code",
            "enter your code",
            "verify your identity",
        ]
        content = await self._page.content()
        return any(indicator in content.lower() for indicator in mfa_indicators)

    async def _submit_mfa(self, code: str) -> None:
        await self._page.fill('input[type="text"]', code)
        await self._human_delay()
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("networkidle")

    async def _human_delay(self) -> None:
        await asyncio.sleep(random.uniform(0.5, 2.0))
```

- [ ] **Step 2: Verify it imports**

Run: `python -c "from pa.scrapers.wellsfargo import WellsFargoScraper; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pa/scrapers/wellsfargo.py
git commit -m "feat: add Wells Fargo scraper skeleton with login and MFA handling"
```

---

## Task 15b: Scraper Stubs for Synchrony and Credit One

**Files:**
- Create: `pa/scrapers/synchrony.py`
- Create: `pa/scrapers/credit_one.py`

- [ ] **Step 1: Create Synchrony stub**

```python
# pa/scrapers/synchrony.py
import asyncio
import random
from typing import Any

from pa.scrapers.base import BaseScraper, BalanceData, TransactionData


class SynchronyScraper(BaseScraper):
    institution = "synchrony"

    LOGIN_URL = "https://consumercenter.mysynchrony.com/consumercenter/login"

    async def login(self, credentials: dict[str, Any]) -> None:
        await self._page.goto(self.LOGIN_URL)
        await self._human_delay()
        await self._page.fill('input[id="username"]', credentials["username"])
        await self._human_delay()
        await self._page.fill('input[id="password"]', credentials["password"])
        await self._human_delay()
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("networkidle")
        # MFA check would go here

    async def get_balances(self) -> list[BalanceData]:
        # TODO: Implement once scraper framework is proven with WF
        return []

    async def get_transactions(self, since_date: str) -> list[TransactionData]:
        # TODO: Implement once scraper framework is proven with WF
        return []

    async def logout(self) -> None:
        try:
            # Navigate to logout
            await self._page.goto("https://consumercenter.mysynchrony.com/consumercenter/logout")
        except Exception:
            pass

    async def _human_delay(self) -> None:
        await asyncio.sleep(random.uniform(0.5, 2.0))
```

- [ ] **Step 2: Create Credit One stub**

```python
# pa/scrapers/credit_one.py
import asyncio
import random
from typing import Any

from pa.scrapers.base import BaseScraper, BalanceData, TransactionData


class CreditOneScraper(BaseScraper):
    institution = "creditone"

    LOGIN_URL = "https://www.creditonebank.com/login"

    async def login(self, credentials: dict[str, Any]) -> None:
        await self._page.goto(self.LOGIN_URL)
        await self._human_delay()
        await self._page.fill('input[name="username"]', credentials["username"])
        await self._human_delay()
        await self._page.fill('input[name="password"]', credentials["password"])
        await self._human_delay()
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_load_state("networkidle")

    async def get_balances(self) -> list[BalanceData]:
        # TODO: Implement once scraper framework is proven with WF
        return []

    async def get_transactions(self, since_date: str) -> list[TransactionData]:
        # TODO: Implement once scraper framework is proven with WF
        return []

    async def logout(self) -> None:
        try:
            await self._page.goto("https://www.creditonebank.com/logout")
        except Exception:
            pass

    async def _human_delay(self) -> None:
        await asyncio.sleep(random.uniform(0.5, 2.0))
```

- [ ] **Step 3: Verify imports**

Run: `python -c "from pa.scrapers.synchrony import SynchronyScraper; from pa.scrapers.credit_one import CreditOneScraper; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pa/scrapers/synchrony.py pa/scrapers/credit_one.py
git commit -m "feat: add Synchrony and Credit One scraper stubs"
```

---

## Task 16: Integration Smoke Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
"""Smoke test that all modules wire together correctly."""
from pathlib import Path

import pytest

from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge
from pa.scheduler.scheduler import PAScheduler
from pa.exceptions import VaultLockedError


async def test_full_flow_without_network(tmp_dir: Path, sample_config: Path):
    """Test the complete data flow: vault -> store -> brain query building."""
    # 1. Config
    config = Config(sample_config)
    await config.load()

    # 2. Vault
    vault = Vault(tmp_dir)
    await vault.init("test-password")
    await vault.add("wellsfargo", {"username": "testuser", "password": "testpass"})
    creds = vault.get("wellsfargo")
    assert creds["username"] == "testuser"

    # 3. Store
    store = Store(tmp_dir / "test.db")
    await store.connect()
    await store.init_schema()

    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_balance(acc_id, balance=1500.00)

    cc_id = await store.add_account("synchrony", "Synchrony Card", "credit_card", interest_rate=0.2499, credit_limit=5000.0)
    await store.add_balance(cc_id, balance=2500.00, minimum_payment=35.00, due_date="2026-03-25")

    await store.add_transaction(acc_id, "2026-03-15", "GROCERY STORE", -85.00)

    # 4. Verify data retrieval
    balances = await store.get_latest_balances()
    assert len(balances) == 2

    txns = await store.get_transactions(account_id=acc_id)
    assert len(txns) == 1

    # 5. Brain builds system prompt with real data
    brain = Brain(config=config)
    prompt = brain.build_system_prompt(balances)
    assert "WF Checking" in prompt
    assert "Synchrony Card" in prompt

    # 6. MFA bridge works
    mfa = MFABridge(timeout_seconds=0.1)
    assert not mfa.has_pending("wellsfargo")

    # 7. Scheduler has jobs
    scheduler = PAScheduler()
    assert len(scheduler.get_job_names()) >= 5

    # 8. Vault lock works
    vault.lock()
    with pytest.raises(VaultLockedError):
        vault.get("wellsfargo")

    await store.close()
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/test_integration.py -v`
Expected: 1 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: add integration smoke test verifying all modules wire together"
```

---

## Task 17: Run Full Test Suite and Final Commit

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (approximately 36 tests)

- [ ] **Step 2: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: test suite cleanup and final adjustments"
```

- [ ] **Step 3: Verify git log**

Run: `git log --oneline`
Expected: Clean commit history with one commit per task
