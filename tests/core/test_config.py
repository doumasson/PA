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
        "llm": {"scrub_untrusted": True, "tiers": {"parse": ["a"]}},
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

async def test_update_writes_local_overlay(config_file: Path):
    config = Config(config_file)
    await config.load()
    await config.update("monthly_income", 6000.0)
    assert config.get("monthly_income") == 6000.0
    # Tracked base file is never touched by runtime updates
    assert json.loads(config_file.read_text())["monthly_income"] == 5000.0
    overlay = json.loads((config_file.parent / "config.local.json").read_text())
    assert overlay["monthly_income"] == 6000.0

async def test_local_overlay_deep_merges(config_file: Path):
    (config_file.parent / "config.local.json").write_text(json.dumps({
        "telegram_user_id": 99,
        "llm": {"tiers": {"parse": ["b"]}},
    }))
    config = Config(config_file)
    await config.load()
    assert config.get("telegram_user_id") == 99          # overlay wins
    assert config.get("monthly_income") == 5000.0        # base survives
    llm = config.get("llm")
    assert llm["tiers"]["parse"] == ["b"]                # nested overlay wins
    assert llm["scrub_untrusted"] is True                # nested sibling survives

async def test_as_dict(config_file: Path):
    config = Config(config_file)
    await config.load()
    assert config.as_dict()["telegram_user_id"] == 12345
