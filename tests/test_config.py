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
