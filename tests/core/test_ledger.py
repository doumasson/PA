from pathlib import Path

import pytest

from pa.core.learning import SCHEMA as LEARNING_SCHEMA
from pa.core.learning import LearningStore
from pa.core.ledger import SCHEMA as LEDGER_SCHEMA
from pa.core.ledger import Ledger, error_signature, guarded
from pa.core.store import Store


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    for stmt in (LEDGER_SCHEMA + LEARNING_SCHEMA).split(";"):
        if stmt.strip():
            await s.execute(stmt)
    yield s
    await s.close()


@pytest.fixture
def sent() -> list[str]:
    return []


@pytest.fixture
def ledger(store, sent) -> Ledger:
    async def notify(text: str) -> None:
        sent.append(text)

    return Ledger(store, notify=notify, learning=LearningStore(store))


# -- error_signature ---------------------------------------------------------


def test_signature_stable_across_volatile_fragments():
    a = error_signature(ValueError("timeout after 30 seconds at 0xdeadbeef on 2026-07-01"), "job")
    b = error_signature(ValueError("timeout after 45 seconds at 0xcafebabe on 2026-07-02"), "job")
    assert a == b


def test_signature_differs_by_type_source_and_message():
    e = ValueError("boom")
    assert error_signature(e, "job_a") != error_signature(e, "job_b")
    assert error_signature(ValueError("boom"), "job") != error_signature(KeyError("boom"), "job")
    assert error_signature(ValueError("boom"), "job") != error_signature(ValueError("bang"), "job")


def test_signature_strips_long_quoted_literals():
    a = error_signature(ValueError(f"bad payload '{'x' * 80}'"), "job")
    b = error_signature(ValueError(f"bad payload '{'y' * 80}'"), "job")
    assert a == b


# -- record -------------------------------------------------------------------


async def test_record_new_error_inserts_and_notifies(ledger, store, sent):
    try:
        raise ValueError("boom")
    except ValueError as e:
        sig = await ledger.record(e, "scraper")
    assert len(sig) == 16
    row = await store.fetchone("SELECT * FROM core_ledger WHERE signature = ?", (sig,))
    assert row["source"] == "scraper"
    assert row["error_type"] == "ValueError"
    assert row["message"] == "boom"
    assert row["count"] == 1
    assert "ValueError" in row["trace"]
    assert len(sent) == 1
    assert "New failure in scraper" in sent[0]


async def test_record_repeat_dedups_by_signature(ledger, store, sent):
    sig1 = await ledger.record(ValueError("boom"), "scraper")
    sig2 = await ledger.record(ValueError("boom"), "scraper")
    assert sig1 == sig2
    row = await store.fetchone("SELECT count FROM core_ledger WHERE signature = ?", (sig1,))
    assert row["count"] == 2
    assert len(sent) == 1  # only the first occurrence notifies (until the burst)


async def test_record_burst_notifies_at_threshold(ledger, sent):
    for _ in range(Ledger.BURST_THRESHOLD + 2):
        await ledger.record(ValueError("boom"), "scraper")
    burst = [m for m in sent if "Recurring failure" in m]
    assert len(burst) == 1  # fires exactly once, at count == 5
    assert "5x" in burst[0]
    assert len(sent) == 2  # new-failure + burst, nothing else


async def test_record_notes_known_fix_for_new_signature(ledger, sent):
    sig = error_signature(ValueError("boom"), "scraper")
    await ledger.remember_fix(sig, "restart the scraper", {"action": "restart"})
    await ledger.record(ValueError("boom"), "scraper")
    assert "Known fix on file: restart the scraper" in sent[0]


async def test_record_survives_broken_notifier(store):
    async def broken(text: str) -> None:
        raise RuntimeError("telegram down")

    ledger = Ledger(store, notify=broken)
    sig = await ledger.record(ValueError("boom"), "scraper")
    assert sig != ""
    row = await store.fetchone("SELECT * FROM core_ledger WHERE signature = ?", (sig,))
    assert row is not None


async def test_record_never_raises_even_when_store_is_broken():
    ledger = Ledger(store=None)
    sig = await ledger.record(ValueError("boom"), "scraper")
    assert sig == ""


async def test_record_without_notifier(store):
    ledger = Ledger(store)
    assert await ledger.record(ValueError("boom"), "scraper") != ""


# -- fixes ---------------------------------------------------------------------


async def test_remember_fix_and_known_fix(ledger):
    await ledger.remember_fix("abc123", "rotate the token", {"action": "reauth"})
    fix = await ledger.known_fix("abc123")
    assert fix is not None
    assert fix["value"] == {"summary": "rotate the token", "action": "reauth"}
    assert fix["confidence"] == 0.7


async def test_known_fix_without_learning_store(store):
    ledger = Ledger(store)
    assert await ledger.known_fix("abc123") is None
    await ledger.remember_fix("abc123", "noop", {})  # must not raise


# -- recent ----------------------------------------------------------------------


async def test_recent_orders_by_last_seen(ledger, store):
    await ledger.record(ValueError("first"), "a")
    await ledger.record(ValueError("second"), "b")
    # CURRENT_TIMESTAMP has second resolution; force a strict ordering.
    await store.execute(
        "UPDATE core_ledger SET last_seen = datetime('now', '+1 hour') WHERE source = 'b'"
    )
    rows = await ledger.recent(limit=1)
    assert len(rows) == 1
    assert rows[0]["source"] == "b"


# -- guarded ----------------------------------------------------------------------


async def test_guarded_passes_through_success(ledger):
    @guarded(ledger, "job")
    async def fine(x: int) -> int:
        return x * 2

    assert await fine(21) == 42
    assert fine.__name__ == "fine"


async def test_guarded_records_failure_and_returns_none(ledger, store, sent):
    @guarded(ledger, "job")
    async def broken() -> None:
        raise RuntimeError("kaput")

    assert await broken() is None
    row = await store.fetchone("SELECT * FROM core_ledger WHERE source = 'job'")
    assert row["error_type"] == "RuntimeError"
    assert len(sent) == 1
