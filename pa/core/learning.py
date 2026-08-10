"""Unified learning store — every LLM escalation deposits an artifact here.

Kinds:
  plan          utterance -> action plan (reflex L0 replay)
  route_rule    keyword/pattern -> intent id
  parse_pattern deterministic extraction rule taught by an L1 parse
  preference    a stated user preference
  fix           error signature -> remedy that worked
Confidence rises on confirm(), falls on demote(); recall prefers
high-confidence, frequently-hit, recently-used learnings.
"""
from __future__ import annotations

import json
import re
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS core_learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    hits INTEGER NOT NULL DEFAULT 0,
    last_used TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, key)
);
CREATE INDEX IF NOT EXISTS idx_core_learnings_kind ON core_learnings(kind);
"""

_WORD = re.compile(r"[a-z0-9']+")


def normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class LearningStore:
    def __init__(self, store):
        self._store = store

    def schema_sql(self) -> str:
        return SCHEMA

    async def remember(
        self,
        kind: str,
        key: str,
        value: Any,
        source: str = "",
        confidence: float = 0.5,
    ) -> int:
        """Insert or update a learning. Returns its id."""
        key = normalize(key) if kind in ("plan", "route_rule") else key
        value_json = json.dumps(value, ensure_ascii=False)
        await self._store.execute(
            "INSERT INTO core_learnings (kind, key, value, source, confidence) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(kind, key) DO UPDATE SET "
            "value = excluded.value, source = excluded.source, "
            "confidence = MAX(core_learnings.confidence, excluded.confidence)",
            (kind, key, value_json, source, confidence),
        )
        row = await self._store.fetchone(
            "SELECT id FROM core_learnings WHERE kind = ? AND key = ?", (kind, key)
        )
        return row["id"]

    async def recall(self, kind: str, key: str) -> dict | None:
        """Exact-key lookup. Marks the learning as used."""
        key_n = normalize(key) if kind in ("plan", "route_rule") else key
        row = await self._store.fetchone(
            "SELECT * FROM core_learnings WHERE kind = ? AND key = ? AND confidence > 0.15",
            (kind, key_n),
        )
        if row is None:
            return None
        await self._touch(row["id"])
        return self._load(row)

    async def similar(self, kind: str, text: str, threshold: float = 0.6) -> dict | None:
        """Best fuzzy match by token Jaccard, boosted by hits and confidence."""
        rows = await self._store.fetchall(
            "SELECT * FROM core_learnings WHERE kind = ? AND confidence > 0.15", (kind,)
        )
        best, best_score = None, 0.0
        for row in rows:
            score = jaccard(text, row["key"])
            score += min(row["hits"], 20) * 0.005 + (row["confidence"] - 0.5) * 0.1
            if score > best_score:
                best, best_score = row, score
        if best is None or best_score < threshold:
            return None
        await self._touch(best["id"])
        return self._load(best)

    async def all_of_kind(self, kind: str, limit: int = 200) -> list[dict]:
        rows = await self._store.fetchall(
            "SELECT * FROM core_learnings WHERE kind = ? AND confidence > 0.15 "
            "ORDER BY confidence DESC, hits DESC LIMIT ?",
            (kind, limit),
        )
        return [self._load(r) for r in rows]

    async def confirm(self, learning_id: int) -> None:
        """This learning produced a good outcome."""
        await self._store.execute(
            "UPDATE core_learnings SET confidence = MIN(1.0, confidence + 0.1), "
            "hits = hits + 1, last_used = CURRENT_TIMESTAMP WHERE id = ?",
            (learning_id,),
        )

    async def demote(self, learning_id: int) -> None:
        """This learning produced a bad outcome. Repeated demotion buries it."""
        await self._store.execute(
            "UPDATE core_learnings SET confidence = MAX(0.0, confidence - 0.25) WHERE id = ?",
            (learning_id,),
        )

    async def forget(self, learning_id: int) -> None:
        await self._store.execute(
            "DELETE FROM core_learnings WHERE id = ?", (learning_id,)
        )

    async def counts(self) -> dict[str, int]:
        rows = await self._store.fetchall(
            "SELECT kind, COUNT(*) AS n FROM core_learnings GROUP BY kind"
        )
        return {r["kind"]: r["n"] for r in rows}

    async def _touch(self, learning_id: int) -> None:
        await self._store.execute(
            "UPDATE core_learnings SET hits = hits + 1, last_used = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (learning_id,),
        )

    @staticmethod
    def _load(row) -> dict:
        d = dict(row)
        d["value"] = json.loads(d["value"])
        return d
