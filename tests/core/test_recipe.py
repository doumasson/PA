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

def test_resolve_credentials():
    from pa.scrapers.recipe import RecipeEngine
    engine = RecipeEngine.__new__(RecipeEngine)
    steps = [
        {"action": "fill", "selector": "#user", "value": "$cred.username"},
        {"action": "fill", "selector": "#pass", "value": "$cred.password"},
    ]
    resolved = engine.resolve_credentials(steps, {"username": "john", "password": "secret"})
    assert resolved[0]["value"] == "john"
    assert resolved[1]["value"] == "secret"


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
    async def test_replay_returns_resolved_steps(self, engine):
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
        assert resolved[2].get("resolved_value") is None

    @pytest.mark.asyncio
    async def test_replay_returns_none_for_missing_recipe(self, engine):
        result = await engine.get_replay_steps("nonexistent", {"username": "u", "password": "p"})
        assert result is None
