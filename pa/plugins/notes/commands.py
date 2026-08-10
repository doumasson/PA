"""Notes plugin — save anything, find everything.

/note stores a fact. /recall (or natural language: "what was that plumber's
name", "when did I mention the gate code") searches your notes AND Albus's
conversation history with SQLite FTS5, then answers from the hits — a cheap
PARSE-tier synthesis over local search results, fully in line with the
reflex-first philosophy.
"""
from __future__ import annotations

import re

from pa.core.brain import Tier
from pa.plugins import AppContext

_FTS_UNSAFE = re.compile(r"[^A-Za-z0-9\s]")


def _fts_query(text: str) -> str:
    """Turn free text into a safe OR-of-terms FTS5 query.

    Strip ALL punctuation (commas broke the FTS5 parser) and double-quote
    every term so FTS keywords like AND/NEAR can't hijack the syntax."""
    terms = [t for t in _FTS_UNSAFE.sub(" ", text).split() if len(t) > 2]
    return " OR ".join(f'"{t}"' for t in terms[:8])


async def save_note(ctx: AppContext, content: str) -> str:
    note_id = await ctx.store.execute(
        "INSERT INTO notes_items (content) VALUES (?)", (content,)
    )
    await ctx.store.execute(
        "INSERT INTO notes_fts (rowid, content) VALUES (?, ?)",
        (note_id, content),
    )
    return f"📌 Noted (#{note_id}): {content[:120]}"


async def search_everything(ctx: AppContext, query: str, limit: int = 6) -> list[dict]:
    """FTS over notes + LIKE scan over recent conversation history."""
    hits: list[dict] = []
    fts = _fts_query(query)
    if fts:
        rows = await ctx.store.fetchall(
            "SELECT n.id, n.content, n.created_at, bm25(notes_fts) AS rank "
            "FROM notes_fts JOIN notes_items n ON n.id = notes_fts.rowid "
            "WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
            (fts, limit),
        )
        hits.extend(
            {"kind": "note", "when": r["created_at"], "text": r["content"]}
            for r in rows
        )
    terms = [t for t in _FTS_UNSAFE.sub(" ", query).split() if len(t) > 3][:3]
    for term in terms:
        rows = await ctx.store.fetchall(
            "SELECT role, content, created_at FROM core_conversations_v2 "
            "WHERE content LIKE ? ORDER BY id DESC LIMIT 3",
            (f"%{term}%",),
        )
        hits.extend(
            {"kind": f"conversation ({r['role']})", "when": r["created_at"],
             "text": r["content"][:300]}
            for r in rows
        )
    seen, unique = set(), []
    for h in hits:
        key = h["text"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique[:limit]


async def answer_from_hits(ctx: AppContext, question: str, hits: list[dict]) -> str:
    if not hits:
        return "I searched my notes and our conversations — nothing on that."
    corpus = "\n\n".join(
        f"[{h['kind']} — {h['when']}]\n{h['text']}" for h in hits
    )
    return await ctx.brain.complete(
        f"Question: {question}\n\nSearch hits from my local memory:\n{corpus}\n\n"
        "Answer the question from these hits (say which one you used). "
        "If they don't actually answer it, say so plainly.",
        tier=Tier.PARSE, context_id=None, max_tokens=400,
    )


async def handle_note(ctx: AppContext, update, context) -> str:
    content = " ".join(context.args or []).strip()
    if not content:
        return "Usage: /note <anything worth remembering>"
    return await save_note(ctx, content)


async def handle_recall(ctx: AppContext, update, context) -> str:
    query = " ".join(context.args or []).strip()
    if not query:
        return "Usage: /recall <what you're trying to remember>"
    hits = await search_everything(ctx, query)
    return await answer_from_hits(ctx, query, hits)


async def handle_notes_nl(ctx: AppContext, text: str, update) -> str:
    text = text.split("\n\n[Context from prior steps:")[0].strip()
    lower = text.lower()
    for prefix in ("note:", "note that ", "remember this:", "remember that ",
                   "save this:", "jot down "):
        if lower.startswith(prefix):
            return await save_note(ctx, text[len(prefix):].strip())
    # Otherwise treat it as a recall question
    hits = await search_everything(ctx, text)
    return await answer_from_hits(ctx, text, hits)
