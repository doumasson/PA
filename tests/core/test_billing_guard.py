"""The owner's standing order: LLM traffic must never hit a paid provider API.
Brain must refuse to construct if any backend points at one."""
import pytest
from pa.core.brain import Brain


def _cfg(base_url, trusted=False):
    return {"llm": {
        "backends": {"b": {"base_url": base_url, "trusted": trusted,
                           "models": {"parse": "m", "reason": "m"}}},
        "tiers": {"parse": ["b"], "reason": ["b"]},
    }}


def test_local_proxy_is_allowed():
    Brain(_cfg("http://localhost:8317/v1"))
    Brain(_cfg("http://127.0.0.1:8317/v1"))


@pytest.mark.parametrize("host", [
    "https://api.anthropic.com/v1",
    "https://api.openai.com/v1",
    "https://api.groq.com/openai/v1",
    "https://generativelanguage.googleapis.com/v1",
])
def test_paid_providers_are_refused(host):
    with pytest.raises(ValueError, match="billing guard"):
        Brain(_cfg(host))


def test_paid_provider_refused_even_if_marked_trusted():
    # trusted governs scrubbing, not billing — a paid host is always refused.
    with pytest.raises(ValueError, match="billing guard"):
        Brain(_cfg("https://api.anthropic.com/v1", trusted=True))


def test_future_home_llm_box_is_allowed():
    # A LAN host the owner opts into (trusted) is fine — this is the swap path.
    Brain(_cfg("http://192.168.1.50:11434/v1", trusted=True))
