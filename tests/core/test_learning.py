from pathlib import Path

import pytest

from pa.core.learning import SCHEMA, LearningStore, jaccard, normalize
from pa.core.store import Store


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


# -- helpers -------------------------------------------------------------


def test_normalize_lowercases_and_strips_punctuation():
    assert normalize("Check My BALANCE!?") == "check my balance"
    assert normalize("what's up") == "what's up"
    assert normalize("") == ""


def test_jaccard():
    assert jaccard("check bank balance", "check bank balance") == 1.0
    assert jaccard("check bank balance", "bank balance check now") == pytest.approx(3 / 4)
    assert jaccard("apples", "oranges") == 0.0
    assert jaccard("", "anything") == 0.0


# -- remember / recall ----------------------------------------------------


async def test_remember_and_recall(learning):
    lid = await learning.remember("plan", "check bank balance", {"actions": [1]})
    assert lid > 0
    hit = await learning.recall("plan", "check bank balance")
    assert hit is not None
    assert hit["id"] == lid
    assert hit["value"] == {"actions": [1]}
    assert hit["confidence"] == 0.5


async def test_recall_normalizes_plan_keys(learning):
    await learning.remember("plan", "Check Bank Balance!", {"a": 1})
    hit = await learning.recall("plan", "check bank balance")
    assert hit is not None


async def test_recall_does_not_normalize_other_kinds(learning, store):
    await learning.remember("fix", "SIG-ABC", {"summary": "restart"})
    row = await store.fetchone("SELECT key FROM core_learnings WHERE kind = 'fix'")
    assert row["key"] == "SIG-ABC"
    assert await learning.recall("fix", "SIG-ABC") is not None


async def test_recall_miss_returns_none(learning):
    assert await learning.recall("plan", "never seen") is None


async def test_recall_marks_used(learning, store):
    lid = await learning.remember("plan", "check bank balance", {})
    await learning.recall("plan", "check bank balance")
    row = await store.fetchone("SELECT hits, last_used FROM core_learnings WHERE id = ?", (lid,))
    assert row["hits"] == 1
    assert row["last_used"] is not None


async def test_remember_upsert_keeps_max_confidence(learning, store):
    lid1 = await learning.remember("plan", "check bank balance", {"v": 1}, confidence=0.8)
    lid2 = await learning.remember("plan", "check bank balance", {"v": 2}, confidence=0.4)
    assert lid1 == lid2
    hit = await learning.recall("plan", "check bank balance")
    assert hit["value"] == {"v": 2}
    assert hit["confidence"] == 0.8


# -- similar ---------------------------------------------------------------


async def test_similar_fuzzy_match(learning):
    lid = await learning.remember("plan", "check bank balance", {"a": 1})
    hit = await learning.similar("plan", "check bank balance now", threshold=0.6)
    assert hit is not None
    assert hit["id"] == lid


async def test_similar_below_threshold_returns_none(learning):
    await learning.remember("plan", "check bank balance", {"a": 1})
    assert await learning.similar("plan", "cook pasta dinner", threshold=0.6) is None


async def test_similar_ignores_other_kinds(learning):
    await learning.remember("route_rule", "check bank balance", {"a": 1})
    assert await learning.similar("plan", "check bank balance") is None


# -- confirm / demote / forget ----------------------------------------------


async def test_confirm_raises_confidence_and_hits(learning, store):
    lid = await learning.remember("plan", "check bank balance", {})
    await learning.confirm(lid)
    row = await store.fetchone("SELECT confidence, hits FROM core_learnings WHERE id = ?", (lid,))
    assert row["confidence"] == pytest.approx(0.6)
    assert row["hits"] == 1


async def test_confirm_caps_at_one(learning, store):
    lid = await learning.remember("plan", "check bank balance", {}, confidence=0.95)
    await learning.confirm(lid)
    row = await store.fetchone("SELECT confidence FROM core_learnings WHERE id = ?", (lid,))
    assert row["confidence"] == 1.0


async def test_demote_buries_learning(learning, store):
    lid = await learning.remember("plan", "check bank balance", {})
    await learning.demote(lid)
    assert (await store.fetchone(
        "SELECT confidence FROM core_learnings WHERE id = ?", (lid,)
    ))["confidence"] == pytest.approx(0.25)
    await learning.demote(lid)
    row = await store.fetchone("SELECT confidence FROM core_learnings WHERE id = ?", (lid,))
    assert row["confidence"] == 0.0
    # Below the 0.15 confidence floor: invisible to recall and similar.
    assert await learning.recall("plan", "check bank balance") is None
    assert await learning.similar("plan", "check bank balance") is None


async def test_demote_floors_at_zero(learning, store):
    lid = await learning.remember("plan", "check bank balance", {}, confidence=0.1)
    await learning.demote(lid)
    row = await store.fetchone("SELECT confidence FROM core_learnings WHERE id = ?", (lid,))
    assert row["confidence"] == 0.0


async def test_forget_deletes(learning, store):
    lid = await learning.remember("preference", "coffee", "black")
    await learning.forget(lid)
    assert await store.fetchone("SELECT * FROM core_learnings WHERE id = ?", (lid,)) is None


# -- all_of_kind / counts -----------------------------------------------------


async def test_all_of_kind_orders_by_confidence(learning):
    await learning.remember("plan", "low key one", {}, confidence=0.3)
    await learning.remember("plan", "high key two", {}, confidence=0.9)
    rows = await learning.all_of_kind("plan")
    assert [r["confidence"] for r in rows] == [0.9, 0.3]


async def test_counts(learning):
    await learning.remember("plan", "check bank balance", {})
    await learning.remember("plan", "cook pasta dinner", {})
    await learning.remember("fix", "SIG-1", {})
    assert await learning.counts() == {"plan": 2, "fix": 1}


async def test_counts_empty(learning):
    assert await learning.counts() == {}
