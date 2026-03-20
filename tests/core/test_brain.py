import json
import pytest
from unittest.mock import patch
from pa.core.brain import Brain
from pa.core.config import Config
from pa.core.tier import Tier


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
