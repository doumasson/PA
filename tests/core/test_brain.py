import copy
from pathlib import Path

import pytest

import pa.core.brain as brain_mod
from pa.core.brain import (
    MAX_TURNS_IN_PROMPT,
    MAX_TURNS_KEPT,
    SCHEMA,
    Brain,
    BrainContext,
    Tier,
)
from pa.core.exceptions import BrainAPIError
from pa.core.store import Store

CONFIG = {
    "llm": {
        "backends": {
            "cloud": {
                "base_url": "http://cloud.test/v1",
                "trusted": False,
                "models": {"parse": "cloud-parse", "reason": "cloud-reason"},
            },
            "local": {
                "base_url": "http://local.test/v1",
                "trusted": True,
                "models": {"parse": "local-parse", "reason": "local-reason"},
            },
        },
        "tiers": {"parse": ["cloud", "local"], "reason": ["local"]},
        "scrub_untrusted": True,
    }
}


class StubCall:
    """Replacement for Brain._call: records calls, returns canned text."""

    def __init__(self, reply: str = "ok", fail_backends: set[str] | None = None):
        self.reply = reply
        self.fail_backends = fail_backends or set()
        self.calls: list[dict] = []

    async def __call__(self, backend, model, messages, max_tokens, temperature):
        self.calls.append({
            "backend": backend.name,
            "model": model,
            "messages": copy.deepcopy(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        if backend.name in self.fail_backends:
            raise RuntimeError(f"{backend.name} is down")
        return self.reply


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr(brain_mod.asyncio, "sleep", _instant)


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            await s.execute(stmt)
    yield s
    await s.close()


def make_brain(reply: str = "ok", fail_backends: set[str] | None = None,
               config: dict | None = None, **kwargs) -> tuple[Brain, StubCall]:
    brain = Brain(config or CONFIG, **kwargs)
    stub = StubCall(reply, fail_backends)
    brain._call = stub
    return brain, stub


class FakeStats:
    def __init__(self):
        self.bumps: list[tuple[str, float]] = []

    async def bump(self, metric: str, value: float = 1.0) -> None:
        self.bumps.append((metric, value))


class FakeLedger:
    def __init__(self):
        self.recorded: list[tuple[BaseException, str]] = []

    async def record(self, err, source):
        self.recorded.append((err, source))
        return "sig"


# -- tier -> backend/model selection ------------------------------------------


async def test_parse_tier_uses_first_backend_and_its_parse_model():
    brain, stub = make_brain()
    await brain.complete("hello", tier=Tier.PARSE)
    assert stub.calls[0]["backend"] == "cloud"
    assert stub.calls[0]["model"] == "cloud-parse"


async def test_reason_tier_uses_its_own_backend_list():
    brain, stub = make_brain()
    await brain.complete("hello", tier=Tier.REASON)
    assert stub.calls[0]["backend"] == "local"
    assert stub.calls[0]["model"] == "local-reason"


async def test_backend_without_tier_model_is_skipped():
    config = copy.deepcopy(CONFIG)
    del config["llm"]["backends"]["cloud"]["models"]["parse"]
    brain, stub = make_brain(config=config)
    await brain.complete("hello", tier=Tier.PARSE)
    assert stub.calls[0]["backend"] == "local"


async def test_no_backends_configured_raises():
    brain = Brain({"llm": {}})
    with pytest.raises(BrainAPIError, match="No LLM backends"):
        await brain.complete("hello")


async def test_successful_call_bumps_backend_tier_metric():
    stats = FakeStats()
    brain, _ = make_brain(stats=stats)
    await brain.complete("hello", tier=Tier.PARSE)
    assert ("llm_calls.cloud.parse", 1.0) in stats.bumps


# -- fallback and retries -------------------------------------------------------


async def test_fallback_to_second_backend_when_first_raises():
    brain, stub = make_brain(reply="from local", fail_backends={"cloud"})
    text = await brain.complete("hello", tier=Tier.PARSE)
    assert text == "from local"
    backends = [c["backend"] for c in stub.calls]
    assert backends == ["cloud", "cloud", "local"]  # 2 retries, then fallback


async def test_all_backends_exhausted_raises_and_records():
    stats = FakeStats()
    ledger = FakeLedger()
    brain, stub = make_brain(fail_backends={"cloud", "local"}, stats=stats, ledger=ledger)
    with pytest.raises(BrainAPIError, match="All backends failed for tier 'parse'"):
        await brain.complete("hello", tier=Tier.PARSE)
    assert len(stub.calls) == 4  # 2 attempts x 2 backends
    assert ("llm_errors", 1.0) in stats.bumps
    assert len(ledger.recorded) == 1
    assert ledger.recorded[0][1] == "brain"


# -- scrubbing --------------------------------------------------------------------


async def test_untrusted_backend_sees_placeholders_and_reply_is_restored():
    brain, stub = make_brain(reply="I emailed [EMAIL_1] as asked.")
    text = await brain.complete("Contact steve@example.com", tier=Tier.PARSE)
    sent = stub.calls[0]["messages"][-1]["content"]
    assert "steve@example.com" not in sent
    assert "[EMAIL_1]" in sent
    assert text == "I emailed steve@example.com as asked."


async def test_trusted_backend_gets_raw_prompt():
    brain, stub = make_brain()
    await brain.complete("Contact steve@example.com", tier=Tier.REASON)  # local, trusted
    assert "steve@example.com" in stub.calls[0]["messages"][-1]["content"]


async def test_scrub_untrusted_false_disables_scrubbing():
    config = copy.deepcopy(CONFIG)
    config["llm"]["scrub_untrusted"] = False
    brain, stub = make_brain(config=config)
    await brain.complete("Contact steve@example.com", tier=Tier.PARSE)
    assert "steve@example.com" in stub.calls[0]["messages"][-1]["content"]


async def test_context_stores_unscrubbed_prompt():
    brain, _ = make_brain(reply="done")
    await brain.complete("Contact steve@example.com", tier=Tier.PARSE, context_id="main")
    assert brain.context("main").turns[0]["content"] == "Contact steve@example.com"


# -- query_json / extract_json ------------------------------------------------------


async def test_query_json_extracts_and_forces_json_system_prompt():
    brain, stub = make_brain(reply='Sure!\n```json\n{"intent": "balance"}\n```')
    result = await brain.query_json("what's my balance", system="You plan actions.")
    assert result == {"intent": "balance"}
    system_msg = stub.calls[0]["messages"][0]
    assert system_msg["role"] == "system"
    assert "You plan actions." in system_msg["content"]
    assert "ONLY a valid JSON object" in system_msg["content"]
    assert stub.calls[0]["temperature"] == 0.0


def test_extract_json_plain_object():
    assert Brain.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_surrounding_prose():
    assert Brain.extract_json('Here you go: {"a": 1} — enjoy!') == {"a": 1}


def test_extract_json_markdown_fence():
    assert Brain.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert Brain.extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_trailing_commas():
    assert Brain.extract_json('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}


def test_extract_json_nested_and_braces_in_strings():
    text = 'noise {"a": {"b": "curly } inside", "c": "quote \\" here"}} tail'
    assert Brain.extract_json(text) == {"a": {"b": "curly } inside", "c": 'quote " here'}}


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError, match="No JSON object"):
        Brain.extract_json("I could not comply.")


def test_extract_json_unmatched_braces_raises():
    with pytest.raises(ValueError, match="Unmatched braces"):
        Brain.extract_json('{"a": 1')


# -- context isolation and conversation memory ----------------------------------


async def test_contexts_are_isolated():
    brain, stub = make_brain()
    await brain.complete("agent A secret", tier=Tier.PARSE, context_id="a")
    await brain.complete("hello from B", tier=Tier.PARSE, context_id="b")
    b_prompt = "\n".join(str(m) for m in stub.calls[1]["messages"])
    assert "agent A secret" not in b_prompt
    assert [t["content"] for t in brain.context("a").turns] == ["agent A secret", "ok"]
    assert [t["content"] for t in brain.context("b").turns] == ["hello from B", "ok"]


async def test_context_history_included_in_later_prompts():
    brain, stub = make_brain()
    await brain.complete("first message", tier=Tier.PARSE, context_id="main")
    await brain.complete("second message", tier=Tier.PARSE, context_id="main")
    roles = [m["role"] for m in stub.calls[1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert stub.calls[1]["messages"][0]["content"] == "first message"


async def test_stateless_call_keeps_no_memory():
    brain, stub = make_brain()
    await brain.complete("one-off", tier=Tier.PARSE, context_id=None)
    assert brain._contexts == {}


async def test_base_system_prompt_and_fragments_prepended():
    brain, stub = make_brain()
    brain.set_base_system_prompt("You are Albus.")
    brain.context("main").system_fragments.append("Finance plugin active.")
    await brain.complete("hi", tier=Tier.PARSE, context_id="main")
    system_msg = stub.calls[0]["messages"][0]
    assert system_msg["role"] == "system"
    assert "You are Albus." in system_msg["content"]
    assert "Finance plugin active." in system_msg["content"]


def test_brain_context_caps_turns_and_window():
    ctx = BrainContext("t")
    for i in range(MAX_TURNS_KEPT + 10):
        ctx.add("user", f"msg {i}")
    assert len(ctx.turns) == MAX_TURNS_KEPT
    assert len(ctx.window()) == MAX_TURNS_IN_PROMPT
    assert ctx.window()[-1]["content"] == f"msg {MAX_TURNS_KEPT + 9}"


# -- persistence ---------------------------------------------------------------------


async def test_turns_persisted_and_reloaded(store):
    brain, _ = make_brain(reply="the answer", store=store)
    await brain.complete("the question", tier=Tier.PARSE, context_id="main")

    reloaded = Brain(CONFIG, store=store)
    await reloaded.load_from_db()
    turns = reloaded.context("main").turns
    assert turns == [
        {"role": "user", "content": "the question"},
        {"role": "assistant", "content": "the answer"},
    ]


async def test_persisted_turns_pruned_to_max_kept(store):
    brain, _ = make_brain(store=store)
    for i in range(MAX_TURNS_KEPT // 2 + 5):
        await brain._record_turns("main", f"q{i}", f"a{i}")
    rows = await store.fetchall(
        "SELECT content FROM core_conversations_v2 WHERE context_id = 'main' ORDER BY id"
    )
    assert len(rows) == MAX_TURNS_KEPT
    assert rows[-1]["content"] == f"a{MAX_TURNS_KEPT // 2 + 4}"  # newest kept
    assert rows[0]["content"] != "q0"  # oldest pruned


async def test_prune_is_per_context(store):
    brain, _ = make_brain(store=store)
    await brain._record_turns("other", "keep me", "ok")
    for i in range(MAX_TURNS_KEPT):
        await brain._record_turns("main", f"q{i}", f"a{i}")
    rows = await store.fetchall(
        "SELECT * FROM core_conversations_v2 WHERE context_id = 'other'"
    )
    assert len(rows) == 2
