from pathlib import Path

import pytest

from pa.core.learning import SCHEMA, LearningStore
from pa.core.reflex import Plan, Reflex, pattern_key
from pa.core.store import Store

CATALOG = [
    {
        "intent_id": "finance.balance",
        "description": "Report current bank balances",
        "examples": ["what's my balance", "how much money do I have"],
    },
    {"intent_id": "meals.plan", "description": "Plan dinner", "examples": []},
]

BALANCE_PLAN = {
    "actions": [{"intent_id": "finance.balance", "reason": "user asked for balance"}],
    "synthesize": False,
}


class FakeBrain:
    """Stands in for Brain; only query_json is exercised by Reflex."""

    def __init__(self, result: dict | Exception | None = None):
        self.result = result if result is not None else {"actions": []}
        self.calls: list[dict] = []

    async def query_json(self, prompt, *, tier=None, system=None, image=None, max_tokens=1024):
        self.calls.append({"prompt": prompt, "system": system})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeStats:
    def __init__(self):
        self.bumps: list[str] = []

    async def bump(self, metric: str, value: float = 1.0) -> None:
        self.bumps.append(metric)


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            await s.execute(stmt)
    yield s
    await s.close()


@pytest.fixture
def learning(store) -> LearningStore:
    return LearningStore(store)


def make_reflex(learning, brain_result=None, stats=None) -> tuple[Reflex, FakeBrain, FakeStats]:
    brain = FakeBrain(brain_result)
    stats = stats or FakeStats()
    reflex = Reflex(learning, brain, stats=stats)
    reflex.set_catalog(CATALOG)
    return reflex, brain, stats


# -- pattern_key -----------------------------------------------------------


def test_pattern_key_drops_stop_words_and_sorts():
    assert pattern_key("Can you check my bank balance please?") == "balance bank check"
    assert pattern_key("check BANK balance") == "balance bank check"


def test_pattern_key_all_stop_words_is_empty():
    assert pattern_key("hey can you please") == ""


# -- routing -----------------------------------------------------------------


async def test_empty_catalog_returns_none_plan(learning):
    reflex, brain, _ = make_reflex(learning, BALANCE_PLAN)
    reflex.set_catalog([])
    plan = await reflex.route("check my bank balance")
    assert plan.source == "none"
    assert plan.actions == []
    assert brain.calls == []


async def test_l1_plans_learns_then_l0_replays_without_brain(learning):
    reflex, brain, stats = make_reflex(learning, BALANCE_PLAN)

    first = await reflex.route("check my bank balance")
    assert first.source == "l1"
    assert first.actions == BALANCE_PLAN["actions"]
    assert first.learning_id is not None
    assert len(brain.calls) == 1
    assert "handled_l1" in stats.bumps
    assert "learnings_created" in stats.bumps

    second = await reflex.route("check my bank balance")
    assert second.source == "l0"
    assert second.actions == BALANCE_PLAN["actions"]
    assert second.learning_id == first.learning_id
    assert len(brain.calls) == 1  # no new LLM call
    assert "handled_l0" in stats.bumps


async def test_l0_similar_match_covers_rephrasings(learning):
    reflex, brain, _ = make_reflex(learning, BALANCE_PLAN)
    await reflex.route("check my bank balance")
    plan = await reflex.route("check my bank balance now")  # extra significant word
    assert plan.source == "l0"
    assert len(brain.calls) == 1


async def test_no_actions_means_general_chat_not_learned(learning, store):
    reflex, brain, stats = make_reflex(learning, {"actions": [], "synthesize": False})
    plan = await reflex.route("tell me something interesting")
    assert plan.source == "none"
    assert plan.learning_id is None
    assert "handled_l2" in stats.bumps
    row = await store.fetchone("SELECT COUNT(*) AS n FROM core_learnings")
    assert row["n"] == 0


async def test_short_key_skips_l0_and_learning(learning, store):
    reflex, brain, _ = make_reflex(learning, BALANCE_PLAN)
    plan = await reflex.route("balance?")  # one significant word
    assert plan.source == "l1"
    assert plan.learning_id is None
    row = await store.fetchone("SELECT COUNT(*) AS n FROM core_learnings")
    assert row["n"] == 0


async def test_malformed_actions_filtered(learning):
    reflex, _, _ = make_reflex(learning, {
        "actions": ["junk", {"reason": "no intent"}, {"intent_id": "finance.balance"}],
        "synthesize": True,
    })
    plan = await reflex.route("check my bank balance")
    assert plan.actions == [{"intent_id": "finance.balance"}]
    assert plan.synthesize is True


async def test_brain_failure_degrades_to_general_chat(learning):
    reflex, _, stats = make_reflex(learning, RuntimeError("LLM down"))
    plan = await reflex.route("check my bank balance")
    assert plan.source == "none"
    assert plan.actions == []
    assert "handled_l2" in stats.bumps


async def test_catalog_and_context_reach_the_planner_prompt(learning):
    reflex, brain, _ = make_reflex(learning, BALANCE_PLAN)
    await reflex.route(
        "check my bank balance",
        recent_context=[{"role": "user", "content": "earlier question"}],
    )
    system = brain.calls[0]["system"]
    assert "finance.balance: Report current bank balances" in system
    assert "what's my balance" in system  # example surfaced in the catalog
    assert "earlier question" in system


async def test_missing_capability_propagates_and_is_not_learned(learning, store):
    reflex, brain, _ = make_reflex(
        learning, {"actions": [], "missing": "a way to delete pending tasks"}
    )
    plan = await reflex.route("kill the track and alert weekly task")
    assert plan.source == "none"
    assert plan.actions == []
    assert plan.missing == "a way to delete pending tasks"
    row = await store.fetchone("SELECT COUNT(*) AS n FROM core_learnings")
    assert row["n"] == 0


async def test_missing_ignored_when_actions_present(learning):
    result = dict(BALANCE_PLAN, missing="should be dropped")
    reflex, brain, _ = make_reflex(learning, result)
    plan = await reflex.route("check my bank balance")
    assert plan.actions and plan.missing == ""


async def test_planner_prompt_forbids_topic_adjacent_actions(learning):
    reflex, brain, _ = make_reflex(learning, BALANCE_PLAN)
    await reflex.route("check my bank balance")
    system = brain.calls[0]["system"]
    assert "missing" in system
    assert "trying beats chatting" not in system


# -- outcome feedback -----------------------------------------------------------


async def test_record_outcome_ok_confirms(learning, store):
    reflex, _, _ = make_reflex(learning, BALANCE_PLAN)
    plan = await reflex.route("check my bank balance")
    await reflex.record_outcome(plan, ok=True)
    row = await store.fetchone(
        "SELECT confidence FROM core_learnings WHERE id = ?", (plan.learning_id,)
    )
    assert row["confidence"] == pytest.approx(0.6)


async def test_record_outcome_demote_until_forgotten(learning):
    reflex, brain, _ = make_reflex(learning, BALANCE_PLAN)
    plan = await reflex.route("check my bank balance")
    assert plan.source == "l1"

    # Two demotions: 0.5 -> 0.25 -> 0.0, below the recall floor.
    await reflex.record_outcome(plan, ok=False)
    await reflex.record_outcome(plan, ok=False)

    again = await reflex.route("check my bank balance")
    assert again.source == "l1"  # buried plan not recalled; back to the LLM
    assert len(brain.calls) == 2


async def test_record_outcome_noop_without_learning_id(learning):
    reflex, _, _ = make_reflex(learning)
    await reflex.record_outcome(Plan(), ok=True)  # must not raise
