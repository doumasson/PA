"""Scraper knowledge store - learns login flows per institution."""
from __future__ import annotations
import json
import datetime


class ScraperKnowledge:
    """Stores and retrieves learned scraping knowledge per institution."""

    def __init__(self, store):
        self._store = store

    async def get(self, institution: str) -> dict | None:
        row = await self._store.fetchone(
            "SELECT knowledge FROM finance_scraper_knowledge WHERE institution = ?",
            (institution,)
        )
        if row:
            return json.loads(row['knowledge'])
        return None

    async def save(self, institution: str, knowledge: dict) -> None:
        now = datetime.datetime.now().isoformat()
        knowledge['last_updated'] = now
        await self._store.execute(
            """INSERT INTO finance_scraper_knowledge (institution, knowledge, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(institution) DO UPDATE SET
               knowledge=excluded.knowledge, updated_at=excluded.updated_at""",
            (institution, json.dumps(knowledge), now)
        )

    async def record_success(self, institution: str) -> None:
        await self._store.execute(
            """UPDATE finance_scraper_knowledge
               SET success_count = success_count + 1, last_success = ?
               WHERE institution = ?""",
            (datetime.datetime.now().isoformat(), institution)
        )

    async def record_failure(self, institution: str, error: str) -> None:
        await self._store.execute(
            """UPDATE finance_scraper_knowledge
               SET failure_count = failure_count + 1, last_error = ?
               WHERE institution = ?""",
            (error[:500], institution)
        )

    async def list_institutions(self) -> list[dict]:
        return await self._store.fetchall(
            "SELECT institution, success_count, failure_count, last_success FROM finance_scraper_knowledge"
        )
