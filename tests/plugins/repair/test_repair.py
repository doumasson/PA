"""Repair plugin + daemon state-machine tests (no subprocesses, no Telegram)."""
import types
from pathlib import Path

import pytest

from pa.core.store import Store
from pa.core.ledger import Ledger
from pa.plugins import validate_plugin
from pa.plugins.repair import RepairPlugin
from pa.plugins.repair.commands import handle_repair_callback, handle_repairs
from pa.plugins.repair.daemon import RepairDaemon, build_diagnosis_prompt
from pa.plugins.repair.jobs import job_repair_notify, job_repair_scan


class FakeBot:
    def __init__(self):
        self.messages: list[str] = []
        self.approvals: list[tuple[str, str, str]] = []

    async def send_message(self, text: str) -> None:
        self.messages.append(text)

    async def send_approval(self, text, approve_data, reject_data, **kw) -> None:
        self.approvals.append((text, approve_data, reject_data))


@pytest.fixture
async def ctx(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    await store.connect()
    ledger = Ledger(store)
    await store.executescript(ledger.schema_sql())
    plugin = RepairPlugin()
    await store.executescript(plugin.schema_sql())
    yield types.SimpleNamespace(store=store, bot=FakeBot(), ledger=ledger)
    await store.close()


async def _seed_burst(store, signature="abc123", count=5):
    await store.execute(
        "INSERT INTO core_ledger (signature, source, error_type, message, trace, count) "
        "VALUES (?, 'job:morning_sync', 'KeyError', 'boom', 'tb', ?)",
        (signature, count),
    )


def test_plugin_passes_contract():
    validate_plugin(RepairPlugin())


def test_diagnosis_prompt_carries_details():
    prompt = build_diagnosis_prompt(
        {"signature": "s1", "detail": "source: x\nerror: KeyError: boom"}
    )
    assert "KeyError: boom" in prompt
    assert "MINIMAL fix" in prompt
    assert "repair/s1" in prompt


async def test_scan_queues_bursts_once(ctx):
    await _seed_burst(ctx.store)
    await job_repair_scan(ctx)
    rows = await ctx.store.fetchall("SELECT * FROM repair_queue")
    assert len(rows) == 1
    assert rows[0]["status"] == "queued"
    assert "KeyError" in rows[0]["detail"]
    assert len(ctx.bot.messages) == 1
    # Second scan must not duplicate or re-notify
    await job_repair_scan(ctx)
    rows = await ctx.store.fetchall("SELECT * FROM repair_queue")
    assert len(rows) == 1
    assert len(ctx.bot.messages) == 1


async def test_scan_ignores_below_threshold_and_own_errors(ctx):
    await _seed_burst(ctx.store, signature="low", count=2)
    await ctx.store.execute(
        "INSERT INTO core_ledger (signature, source, error_type, message, count) "
        "VALUES ('own', 'repair_daemon', 'X', 'y', 9)"
    )
    await job_repair_scan(ctx)
    assert await ctx.store.fetchall("SELECT * FROM repair_queue") == []


async def test_notify_sends_approval_then_outcome(ctx):
    await ctx.store.execute(
        "INSERT INTO repair_queue (signature, source, status, summary, diff) "
        "VALUES ('s1', 'job:x', 'awaiting_approval', 'Fix the thing', '+ fixed')"
    )
    await job_repair_notify(ctx)
    assert len(ctx.bot.approvals) == 1
    text, approve, reject = ctx.bot.approvals[0]
    assert "Fix the thing" in text and "+ fixed" in text
    assert approve == "repair:approve:1" and reject == "repair:reject:1"
    row = await ctx.store.fetchone("SELECT notified FROM repair_queue WHERE id = 1")
    assert row["notified"] == 1
    # No duplicate approval on next tick
    await job_repair_notify(ctx)
    assert len(ctx.bot.approvals) == 1
    # Outcome notification after daemon applies
    await ctx.store.execute(
        "UPDATE repair_queue SET status = 'applied' WHERE id = 1"
    )
    await job_repair_notify(ctx)
    assert any("Repair #1" in m for m in ctx.bot.messages)
    row = await ctx.store.fetchone("SELECT notified FROM repair_queue WHERE id = 1")
    assert row["notified"] == 2


async def test_callback_approve_and_reject(ctx):
    await ctx.store.execute(
        "INSERT INTO repair_queue (signature, source, status, notified) "
        "VALUES ('s1', 'job:x', 'awaiting_approval', 1)"
    )
    msg = await handle_repair_callback(ctx, None, "approve:1")
    assert "approved" in msg
    row = await ctx.store.fetchone("SELECT status FROM repair_queue WHERE id = 1")
    assert row["status"] == "approved"
    # Re-approving an already-approved repair is a no-op with a clear message
    msg = await handle_repair_callback(ctx, None, "approve:1")
    assert "already approved" in msg
    # Reject path
    await ctx.store.execute(
        "INSERT INTO repair_queue (signature, source, status, notified) "
        "VALUES ('s2', 'job:y', 'awaiting_approval', 1)"
    )
    msg = await handle_repair_callback(ctx, None, "reject:2")
    row = await ctx.store.fetchone("SELECT status FROM repair_queue WHERE id = 2")
    assert row["status"] == "rejected"
    # Garbage payloads don't explode
    assert "sense" in await handle_repair_callback(ctx, None, "approve:zzz")
    assert "no longer exists" in await handle_repair_callback(ctx, None, "approve:99")


async def test_repairs_command_lists(ctx):
    assert "empty" in await handle_repairs(ctx, None, None)
    await ctx.store.execute(
        "INSERT INTO repair_queue (signature, source, status, summary) "
        "VALUES ('s1', 'job:x', 'applied', 'Fixed it')"
    )
    out = await handle_repairs(ctx, None, None)
    assert "#1" in out and "applied" in out and "Fixed it" in out


async def test_daemon_recovers_stuck_diagnosis(ctx):
    await ctx.store.execute(
        "INSERT INTO repair_queue (signature, source, status, updated_at) "
        "VALUES ('s1', 'job:x', 'diagnosing', datetime('now', '-2 hours'))"
    )
    daemon = RepairDaemon(ctx.store)
    await daemon._recover_stuck()
    row = await ctx.store.fetchone("SELECT status FROM repair_queue WHERE id = 1")
    assert row["status"] == "queued"
    # Fresh diagnosis is left alone
    await ctx.store.execute(
        "INSERT INTO repair_queue (signature, source, status) "
        "VALUES ('s2', 'job:y', 'diagnosing')"
    )
    await daemon._recover_stuck()
    row = await ctx.store.fetchone("SELECT status FROM repair_queue WHERE id = 2")
    assert row["status"] == "diagnosing"


async def test_daemon_set_updates_fields(ctx):
    await ctx.store.execute(
        "INSERT INTO repair_queue (signature, source) VALUES ('s1', 'job:x')"
    )
    daemon = RepairDaemon(ctx.store)
    await daemon._set(1, "awaiting_approval", diff="+ x", summary="did a thing")
    row = await ctx.store.fetchone("SELECT * FROM repair_queue WHERE id = 1")
    assert row["status"] == "awaiting_approval"
    assert row["diff"] == "+ x" and row["summary"] == "did a thing"
