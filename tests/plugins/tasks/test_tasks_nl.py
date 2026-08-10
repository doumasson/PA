"""Tasks plugin — conversational close ("kill that task") and list."""
import types
from pathlib import Path

import pytest

from pa.core.store import Store
from pa.plugins import validate_plugin
from pa.plugins.tasks import TasksPlugin
from pa.plugins.tasks.nl import handle_task_close_nl, handle_task_list_nl


class FakeBrain:
    def __init__(self, result=None):
        self.result = result or {"close": []}
        self.calls = []

    async def query_json(self, prompt, *, tier=None, system=None, **kw):
        self.calls.append({"prompt": prompt, "system": system})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeScheduler:
    def __init__(self):
        self.removed = []

    async def remove_dynamic_job(self, name):
        self.removed.append(name)


@pytest.fixture
async def ctx(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    await store.connect()
    await store.executescript(TasksPlugin().schema_sql())
    c = types.SimpleNamespace(
        store=store, brain=FakeBrain(), scheduler=FakeScheduler(), ledger=None
    )
    yield c
    await store.close()


async def seed(ctx, title, due_date=None, recurring=None):
    return await ctx.store.execute(
        "INSERT INTO tasks_items (title, due_date, recurring) VALUES (?, ?, ?)",
        (title, due_date, recurring),
    )


def test_plugin_contract_and_new_intents():
    plugin = TasksPlugin()
    validate_plugin(plugin)
    intents = {h.intent_id for h in plugin.nl_handlers()}
    assert {"tasks.reminder", "tasks.complete", "tasks.list"} <= intents


async def test_kill_marks_cancelled_and_unschedules_recurring(ctx):
    tid = await seed(ctx, "Track and alert weekly", "2026-04-07", recurring="weekly")
    ctx.brain.result = {"close": [{"id": tid, "status": "cancelled"}]}
    reply = await handle_task_close_nl(ctx, "kill the track and alert weekly", None)
    assert "Killed" in reply and "Track and alert weekly" in reply
    row = await ctx.store.fetchone("SELECT status FROM tasks_items WHERE id = ?", (tid,))
    assert row["status"] == "cancelled"
    assert ctx.scheduler.removed == [f"recurring_task_{tid}"]
    # the real pending list reached the matching prompt
    assert "Track and alert weekly" in ctx.brain.calls[0]["system"]


async def test_finished_marks_done_with_timestamp(ctx):
    tid = await seed(ctx, "IRS bill")
    ctx.brain.result = {"close": [{"id": tid, "status": "done"}]}
    reply = await handle_task_close_nl(ctx, "I already paid the IRS bill", None)
    assert "Done" in reply
    row = await ctx.store.fetchone(
        "SELECT status, completed_at FROM tasks_items WHERE id = ?", (tid,)
    )
    assert row["status"] == "done" and row["completed_at"] is not None


async def test_no_match_lists_open_tasks_instead_of_guessing(ctx):
    await seed(ctx, "IRS bill")
    ctx.brain.result = {"close": []}
    reply = await handle_task_close_nl(ctx, "kill the thingamajig", None)
    assert "couldn't match" in reply.lower()
    assert "IRS bill" in reply
    row = await ctx.store.fetchone(
        "SELECT COUNT(*) AS n FROM tasks_items WHERE status != 'pending'"
    )
    assert row["n"] == 0


async def test_hallucinated_task_id_is_ignored(ctx):
    await seed(ctx, "IRS bill")
    ctx.brain.result = {"close": [{"id": 999, "status": "done"}]}
    reply = await handle_task_close_nl(ctx, "done with the thing", None)
    assert "couldn't match" in reply.lower()


async def test_close_with_nothing_pending(ctx):
    reply = await handle_task_close_nl(ctx, "kill the old task", None)
    assert "no pending tasks" in reply.lower()


async def test_llm_substitution_of_unrelated_task_is_blocked(ctx):
    """Incident 2026-07-05: 'Track and alert weekly - get rid of it' killed
    'IRS bill' because the matcher substituted the only pending task."""
    irs = await seed(ctx, "IRS bill")
    await ctx.store.execute(
        "UPDATE tasks_items SET status = 'cancelled' WHERE id = ?",
        (await seed(ctx, "Track and alert weekly"),),
    )
    ctx.brain.result = {"close": [{"id": irs, "status": "cancelled"}]}
    reply = await handle_task_close_nl(ctx, "Track and alert weekly - get rid of it", None)
    row = await ctx.store.fetchone("SELECT status FROM tasks_items WHERE id = ?", (irs,))
    assert row["status"] == "pending"          # untouched
    assert "already cancelled" in reply.lower()  # and the real answer given


async def test_already_closed_task_reported_when_nothing_pending(ctx):
    tid = await seed(ctx, "Track and alert weekly")
    await ctx.store.execute(
        "UPDATE tasks_items SET status = 'cancelled' WHERE id = ?", (tid,)
    )
    reply = await handle_task_close_nl(ctx, "get rid of track and alert weekly", None)
    assert "already cancelled" in reply.lower()


async def test_explicit_task_number_counts_as_reference(ctx):
    tid = await seed(ctx, "IRS bill")
    ctx.brain.result = {"close": [{"id": tid, "status": "done"}]}
    reply = await handle_task_close_nl(ctx, f"mark task {tid} done", None)
    assert "Done" in reply


async def test_list_flags_overdue(ctx):
    await seed(ctx, "Track and alert weekly", "2026-04-07")
    await seed(ctx, "File taxes", "2099-01-01")
    reply = await handle_task_list_nl(ctx, "what's on my list", None)
    lines = reply.splitlines()
    overdue = [l for l in lines if "Track and alert weekly" in l]
    future = [l for l in lines if "File taxes" in l]
    assert overdue and "OVERDUE" in overdue[0]
    assert future and "OVERDUE" not in future[0]
