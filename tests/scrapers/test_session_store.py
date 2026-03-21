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
