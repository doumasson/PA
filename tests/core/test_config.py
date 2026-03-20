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
    reloaded = json.loads(config_file.read_text())
    assert reloaded["monthly_income"] == 6000.0
