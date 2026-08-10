"""Notes plugin — FTS save/recall and the weekly self-report."""
import types
from pathlib import Path

import pytest

from pa.core.brain import Brain
from pa.core.store import Store
from pa.plugins import validate_plugin
from pa.plugins.notes import NotesPlugin
from pa.plugins.notes.commands import (
    _fts_query,
    handle_notes_nl,
    save_note,
    search_everything,
)


class FakeBrain:
    def __init__(self):
        self.calls = []

    async def complete(self, prompt, **kw):
        self.calls.append(prompt)
        return "synthesized answer"


@pytest.fixture
async def ctx(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    await store.connect()
    await store.executescript(NotesPlugin().schema_sql())
    # conversation table for cross-search
    await store.executescript(Brain({}).schema_sql())
    yield types.SimpleNamespace(store=store, brain=FakeBrain())
    await store.close()


def test_plugin_passes_contract():
    validate_plugin(NotesPlugin())


def test_fts_query_sanitizes():
    q = _fts_query('what was the "plumber\'s" (name)?')
    assert "(" not in q and "," not in q
    assert '"plumber' in q and " OR " in q
    # every term is double-quoted so FTS keywords/punctuation can't break syntax
    q2 = _fts_query("lets do set some guardrails, and near the house")
    for term in q2.split(" OR "):
        assert term.startswith('"') and term.endswith('"')


async def test_save_and_fts_recall(ctx):
    await save_note(ctx, "gate code for the side fence is 4482")
    await save_note(ctx, "plumber was Mike from Parker Plumbing, $180 callout")
    hits = await search_everything(ctx, "what was the plumber's name")
    assert any("Mike" in h["text"] for h in hits)
    assert all(h["kind"] == "note" for h in hits if "Mike" in h["text"])


async def test_search_covers_conversations(ctx):
    await ctx.store.execute(
        "INSERT INTO core_conversations_v2 (context_id, role, content) "
        "VALUES ('main', 'user', 'the furnace filter is a 16x25x1')"
    )
    hits = await search_everything(ctx, "which furnace filter size")
    assert any("16x25x1" in h["text"] for h in hits)


async def test_nl_note_prefixes_save(ctx):
    out = await handle_notes_nl(ctx, "note: trash pickup moved to Thursday", None)
    assert out.startswith("📌")
    row = await ctx.store.fetchone("SELECT content FROM notes_items WHERE id = 1")
    assert "Thursday" in row["content"]


async def test_nl_question_synthesizes_from_hits(ctx):
    await save_note(ctx, "wifi guest password is duckling-parade-42")
    out = await handle_notes_nl(ctx, "what was that guest wifi password", None)
    assert out == "synthesized answer"
    assert "duckling-parade-42" in ctx.brain.calls[0]


async def test_recall_with_no_hits_is_honest(ctx):
    out = await handle_notes_nl(ctx, "what did i say about submarines", None)
    assert "nothing" in out.lower()
    assert ctx.brain.calls == []


async def test_weekly_self_report_sends(tmp_path: Path):
    from pa.core.learning import LearningStore
    from pa.core.ledger import Ledger
    from pa.core.selfreport import weekly_self_report
    from pa.core.stats import Stats
    from pa.plugins.repair import RepairPlugin

    store = Store(tmp_path / "r.db")
    await store.connect()
    learning, ledger, stats = LearningStore(store), Ledger(store), Stats(store)
    for m in (learning, ledger, stats):
        await store.executescript(m.schema_sql())
    await store.executescript(RepairPlugin().schema_sql())
    await stats.bump("handled_l0", 9)
    await stats.bump("handled_l1", 1)
    await learning.remember("plan", "spend amazon", {"actions": []}, source="t")

    sent = []
    bot = types.SimpleNamespace()
    async def send(text): sent.append(text)
    bot.send_message = send
    ctx = types.SimpleNamespace(
        store=store, stats=stats, learning=learning, ledger=ledger, bot=bot
    )
    await weekly_self_report(ctx)
    assert len(sent) == 1
    assert "Self-Report" in sent[0] and "90%" in sent[0]
    await store.close()
