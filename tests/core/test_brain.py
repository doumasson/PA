import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
def mock_client():
    client = MagicMock()
    client.messages.create = AsyncMock()
    return client


@pytest.fixture
async def brain(mock_config, mock_client):
    config = Config(mock_config)
    await config.load()
    with patch.dict("os.environ", {"PA_CLAUDE_API_KEY": "test-key"}):
        b = Brain(config=config)
        b._client = mock_client
        return b


def _mock_response(text: str):
    usage = MagicMock()
    usage.input_tokens = 10
    usage.output_tokens = 10
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.usage = usage
    response.content = [content_block]
    return response


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
        import time
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
