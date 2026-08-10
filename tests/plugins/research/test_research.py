"""Research plugin handler and job tests — fake brain, fake web, tmp SQLite."""
import json
import types
from pathlib import Path

import pytest

from pa.core.brain import Tier
from pa.core.store import Store
from pa.plugins import validate_plugin
from pa.plugins.research import ResearchPlugin, web
from pa.plugins.research.handlers import (
    WEB_FALLBACK_PREFIX,
    do_research,
    handle_research,
    handle_research_nl,
    handle_watch,
    handle_watchlist,
)
from pa.plugins.research.jobs import job_watchlist_update
from pa.plugins.research.web import SearchResult


class FakeBrain:
    def __init__(self):
        self.json_response = {"queries": ["query one", "query two"]}
        self.json_raises = False
        self.text_response = "Synthesized answer with facts [1] and figures [2]."
        self.json_calls = []
        self.complete_calls = []

    async def query_json(self, prompt, **kw):
        self.json_calls.append((prompt, kw))
        if self.json_raises:
            raise RuntimeError("backend down")
        return self.json_response

    async def complete(self, prompt, **kw):
        self.complete_calls.append((prompt, kw))
        return self.text_response


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, text=""):
        self.message = FakeMessage(text)


@pytest.fixture
async def ctx(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    await store.connect()
    await store.executescript(ResearchPlugin().schema_sql())
    yield types.SimpleNamespace(store=store, brain=FakeBrain(), bot=None)
    await store.close()


def wire_web(monkeypatch, results_by_query=None, pages=None):
    """Monkeypatch web.search / web.fetch_readable; return call trackers."""
    searches, fetches = [], []
    results_by_query = results_by_query or {}
    pages = pages or {}

    async def fake_search(query, max_results=5):
        searches.append(query)
        return results_by_query.get(query, results_by_query.get("*", []))

    async def fake_fetch(url, max_chars=6000):
        fetches.append(url)
        return pages.get(url)

    monkeypatch.setattr(web, "search", fake_search)
    monkeypatch.setattr(web, "fetch_readable", fake_fetch)
    return searches, fetches


def test_plugin_passes_contract():
    validate_plugin(ResearchPlugin())


# -- do_research ------------------------------------------------------------------


async def test_do_research_searches_fetches_synthesizes_cites(ctx, monkeypatch):
    searches, fetches = wire_web(
        monkeypatch,
        results_by_query={"*": [
            SearchResult("https://a.com/1", "A", "sa"),
            SearchResult("https://b.com/2", "B", "sb"),
        ]},
        pages={
            "https://a.com/1": "alpha facts from page a",
            "https://b.com/2": "beta facts from page b",
        },
    )

    out = await do_research(ctx, "quantum widgets")

    # PARSE-tier query generation drove two searches
    assert ctx.brain.json_calls[0][1]["tier"] is Tier.PARSE
    assert searches == ["query one", "query two"]
    # deduped URLs fetched once each
    assert sorted(fetches) == ["https://a.com/1", "https://b.com/2"]

    # REASON-tier synthesis saw labeled sources
    prompt, kw = ctx.brain.complete_calls[-1]
    assert kw["tier"] is Tier.REASON
    assert kw["max_tokens"] == 2000
    assert "[1] https://a.com/1" in prompt
    assert "alpha facts from page a" in prompt
    assert "[2] https://b.com/2" in prompt
    assert "quantum widgets" in prompt

    # user-facing result: answer + source list
    assert ctx.brain.text_response in out
    assert "Sources:" in out
    assert "https://b.com/2" in out
    assert not out.startswith(WEB_FALLBACK_PREFIX)

    # stored with sources populated as a JSON array
    row = await ctx.store.fetchone(
        "SELECT query, summary, sources FROM research_queries"
    )
    assert row["query"] == "quantum widgets"
    assert ctx.brain.text_response.startswith(row["summary"][:20])
    assert json.loads(row["sources"]) == ["https://a.com/1", "https://b.com/2"]


async def test_do_research_falls_back_when_offline(ctx, monkeypatch):
    wire_web(monkeypatch)  # search returns [], nothing fetchable

    out = await do_research(ctx, "quantum widgets")

    assert out.startswith(WEB_FALLBACK_PREFIX)
    assert ctx.brain.text_response in out
    # memory answer came from the REASON tier
    prompt, kw = ctx.brain.complete_calls[-1]
    assert kw["tier"] is Tier.REASON
    assert "quantum widgets" in prompt

    row = await ctx.store.fetchone("SELECT summary, sources FROM research_queries")
    assert json.loads(row["sources"]) == []
    assert row["summary"].startswith(WEB_FALLBACK_PREFIX)


async def test_do_research_falls_back_when_all_fetches_fail(ctx, monkeypatch):
    wire_web(
        monkeypatch,
        results_by_query={"*": [SearchResult("https://dead.com/x", "D", "")]},
        pages={},  # fetch_readable -> None for every URL
    )
    out = await do_research(ctx, "topic")
    assert out.startswith(WEB_FALLBACK_PREFIX)


async def test_query_generation_failure_searches_raw_topic(ctx, monkeypatch):
    ctx.brain.json_raises = True
    searches, _ = wire_web(monkeypatch)
    out = await do_research(ctx, "obscure topic")
    assert searches == ["obscure topic"]
    assert out.startswith(WEB_FALLBACK_PREFIX)  # nothing found -> memory


# -- command / NL surface -----------------------------------------------------------


async def test_handle_research_usage(ctx):
    assert await handle_research(ctx, FakeUpdate("/research"), None) == "Usage: /research <topic>"


async def test_handle_research_runs_pipeline(ctx, monkeypatch):
    called = []

    async def fake_do_research(c, topic):
        called.append(topic)
        return "short answer"

    monkeypatch.setattr("pa.plugins.research.handlers.do_research", fake_do_research)
    update = FakeUpdate("/research quantum widgets")
    out = await handle_research(ctx, update, None)
    assert called == ["quantum widgets"]
    assert out == "short answer"
    assert update.message.replies  # progress message was sent


async def test_handle_research_nl_strips_prefix(ctx, monkeypatch):
    called = []

    async def fake_do_research(c, topic):
        called.append(topic)
        return "answer"

    monkeypatch.setattr("pa.plugins.research.handlers.do_research", fake_do_research)
    out = await handle_research_nl(ctx, "tell me about bitcoin", FakeUpdate())
    assert called == ["bitcoin"]
    assert out == "answer"


async def test_watch_and_watchlist(ctx):
    out = await handle_watch(ctx, FakeUpdate("/watch solar prices"), None)
    assert "Now watching: solar prices" in out
    out = await handle_watch(ctx, FakeUpdate("/watch solar prices"), None)
    assert "Already watching" in out
    out = await handle_watchlist(ctx, FakeUpdate("/watchlist"), None)
    assert "solar prices" in out


# -- watchlist job ----------------------------------------------------------------


async def test_watchlist_job_uses_web_pipeline(ctx, monkeypatch):
    searches, fetches = wire_web(
        monkeypatch,
        results_by_query={"*": [
            SearchResult("https://news.com/a", "N", ""),
            SearchResult("https://blog.com/b", "B", ""),
            SearchResult("https://extra.com/c", "E", ""),
        ]},
        pages={
            "https://news.com/a": "big development happened",
            "https://blog.com/b": "more details on the development",
            "https://extra.com/c": "should not be fetched",
        },
    )
    sent = []
    ctx.bot = types.SimpleNamespace()
    async def send(text): sent.append(text)
    ctx.bot.send_message = send

    await ctx.store.execute(
        "INSERT INTO research_watchlist (topic, last_summary) VALUES (?, ?)",
        ("solar prices", "old summary"),
    )

    await job_watchlist_update(ctx)

    # one search (the topic itself), only two pages fetched
    assert searches == ["solar prices"]
    assert len(fetches) == 2

    prompt, kw = ctx.brain.complete_calls[-1]
    assert kw["tier"] is Tier.REASON
    assert "[1] https://news.com/a" in prompt
    assert "big development happened" in prompt
    assert "old summary" in prompt

    row = await ctx.store.fetchone(
        "SELECT last_checked, last_summary FROM research_watchlist"
    )
    assert row["last_checked"]
    assert ctx.brain.text_response[:30] in row["last_summary"]

    hist = await ctx.store.fetchone(
        "SELECT query, sources FROM research_queries WHERE query LIKE '[watchlist]%'"
    )
    assert json.loads(hist["sources"]) == ["https://news.com/a", "https://blog.com/b"]

    assert len(sent) == 1 and "solar prices" in sent[0]


async def test_watchlist_job_offline_flags_memory_answer(ctx, monkeypatch):
    wire_web(monkeypatch)  # web unreachable
    await ctx.store.execute(
        "INSERT INTO research_watchlist (topic) VALUES (?)", ("solar prices",)
    )

    await job_watchlist_update(ctx)

    row = await ctx.store.fetchone("SELECT last_summary FROM research_watchlist")
    assert row["last_summary"].startswith(WEB_FALLBACK_PREFIX)
    hist = await ctx.store.fetchone(
        "SELECT sources FROM research_queries WHERE query LIKE '[watchlist]%'"
    )
    assert json.loads(hist["sources"]) == []
