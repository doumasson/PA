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
