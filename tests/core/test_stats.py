import datetime
from pathlib import Path

import pytest

from pa.core.stats import SCHEMA, Stats
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
def stats(store) -> Stats:
    return Stats(store)


async def _bump_on(store, day: datetime.date, metric: str, value: float) -> None:
    await store.execute(
        "INSERT INTO core_stats (day, metric, value) VALUES (?, ?, ?)",
        (day.isoformat(), metric, value),
    )


async def test_bump_inserts_then_accumulates(stats, store):
    await stats.bump("handled_l0")
    await stats.bump("handled_l0", 2.0)
    row = await store.fetchone(
        "SELECT value FROM core_stats WHERE metric = 'handled_l0'"
    )
    assert row["value"] == 3.0


async def test_bump_keeps_metrics_separate(stats):
    await stats.bump("handled_l0")
    await stats.bump("handled_l1", 5.0)
    w = await stats.window(1)
    assert w == {"handled_l0": 1.0, "handled_l1": 5.0}


async def test_window_sums_days_and_excludes_old_ones(stats, store):
    today = datetime.date.today()
    await _bump_on(store, today - datetime.timedelta(days=3), "handled_l0", 2.0)
    await _bump_on(store, today - datetime.timedelta(days=30), "handled_l0", 99.0)
    await stats.bump("handled_l0", 1.0)
    w = await stats.window(7)
    assert w["handled_l0"] == 3.0


async def test_window_empty(stats):
    assert await stats.window(7) == {}


async def test_reflex_report_rate_and_counts(stats):
    await stats.bump("handled_l0", 3.0)
    await stats.bump("handled_l1", 1.0)
    await stats.bump("learnings_created", 2.0)
    report = await stats.reflex_report()
    assert "75% of 4 requests this week" in report
    assert "parse 1" in report
    assert "Learnings created this week: 2" in report


async def test_reflex_report_trend_up(stats, store):
    last_week = datetime.date.today() - datetime.timedelta(days=10)
    await _bump_on(store, last_week, "handled_l0", 1.0)
    await _bump_on(store, last_week, "handled_l1", 9.0)  # 10% reflex last week
    await stats.bump("handled_l0", 9.0)
    await stats.bump("handled_l1", 1.0)  # 90% this week
    report = await stats.reflex_report()
    assert "↑" in report
    assert "vs 10% last week" in report


async def test_reflex_report_backend_breakdown(stats):
    await stats.bump("llm_calls.cliproxy.parse", 4.0)
    await stats.bump("llm_calls.cliproxy.reason", 1.0)
    report = await stats.reflex_report()
    assert "By backend/tier:" in report
    assert "cliproxy.parse: 4" in report
    assert "cliproxy.reason: 1" in report


async def test_reflex_report_empty_store(stats):
    report = await stats.reflex_report()
    assert "0% of 0 requests" in report
    assert "By backend/tier:" not in report
