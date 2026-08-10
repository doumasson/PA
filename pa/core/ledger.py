"""Error ledger — failures are loud, deduplicated, and remembered.

Every job/handler error lands here with a stable signature. First occurrence
notifies the owner; repeats are counted; bursts escalate. Known signatures
can carry a remembered fix (learning kind='fix') — Phase 3 automates applying
them.
"""
from __future__ import annotations

import hashlib
import logging
import re
import traceback

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS core_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL,
    trace TEXT,
    count INTEGER NOT NULL DEFAULT 1,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notified_at TIMESTAMP
);
"""

# Strip volatile fragments so the same logical error hashes identically.
_VOLATILE = [
    (re.compile(r"0x[0-9a-f]+"), "0xADDR"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]?[\d:.]*\b"), "DATE"),
    (re.compile(r"\b\d+\b"), "N"),
    (re.compile(r"'[^']{40,}'"), "'...'"),
]


def error_signature(err: BaseException, source: str) -> str:
    msg = str(err)
    for pattern, repl in _VOLATILE:
        msg = pattern.sub(repl, msg)
    raw = f"{source}|{type(err).__name__}|{msg[:300]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Ledger:
    # After this many repeats within one signature, escalate wording.
    BURST_THRESHOLD = 5

    def __init__(self, store, notify=None, learning=None):
        """notify: async callable(str) -> None (bot.send_message); optional."""
        self._store = store
        self._notify = notify
        self._learning = learning

    def schema_sql(self) -> str:
        return SCHEMA

    def set_notifier(self, notify) -> None:
        self._notify = notify

    async def record(self, err: BaseException, source: str) -> str:
        """Record an error. Returns its signature. Never raises."""
        try:
            sig = error_signature(err, source)
            trace = "".join(
                traceback.format_exception(type(err), err, err.__traceback__)
            )[-4000:]
            existing = await self._store.fetchone(
                "SELECT id, count, notified_at FROM core_ledger WHERE signature = ?",
                (sig,),
            )
            if existing:
                await self._store.execute(
                    "UPDATE core_ledger SET count = count + 1, "
                    "last_seen = CURRENT_TIMESTAMP, message = ?, trace = ? "
                    "WHERE signature = ?",
                    (str(err)[:500], trace, sig),
                )
                count = existing["count"] + 1
                # Notify at the burst threshold, then keep re-notifying at most
                # once a day while it recurs — a permafail must never go quiet
                # after a single warning.
                stale = await self._store.fetchone(
                    "SELECT 1 FROM core_ledger WHERE signature = ? AND "
                    "(notified_at IS NULL OR notified_at < datetime('now', '-24 hours'))",
                    (sig,),
                )
                if count >= self.BURST_THRESHOLD and (
                    count == self.BURST_THRESHOLD or stale
                ):
                    fix = await self.known_fix(sig)
                    fix_note = (
                        f"\nKnown fix on file: {fix['value'].get('summary', '?')}"
                        if fix else ""
                    )
                    await self._send(
                        f"⚠️ Recurring failure in {source} ({count}x): "
                        f"{type(err).__name__}: {str(err)[:200]}\n"
                        f"Signature {sig} — this keeps happening.{fix_note}"
                    )
                    await self._store.execute(
                        "UPDATE core_ledger SET notified_at = CURRENT_TIMESTAMP "
                        "WHERE signature = ?",
                        (sig,),
                    )
            else:
                await self._store.execute(
                    "INSERT INTO core_ledger "
                    "(signature, source, error_type, message, trace) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sig, source, type(err).__name__, str(err)[:500], trace),
                )
                fix = await self.known_fix(sig)
                fix_note = f"\nKnown fix on file: {fix['value'].get('summary', '?')}" if fix else ""
                await self._send(
                    f"❌ New failure in {source}: "
                    f"{type(err).__name__}: {str(err)[:200]}{fix_note}"
                )
            logger.error("[%s] %s: %s", source, type(err).__name__, err, exc_info=err)
            return sig
        except Exception:
            # The ledger must never take the app down, but it also must not
            # hide the original problem.
            logger.exception("Ledger failed while recording an error from %s", source)
            return ""

    async def known_fix(self, signature: str) -> dict | None:
        if self._learning is None:
            return None
        return await self._learning.recall("fix", signature)

    async def remember_fix(self, signature: str, summary: str, remedy: dict) -> None:
        """Record what fixed this signature (consulted on recurrence; Phase 3 automates)."""
        if self._learning is None:
            return
        await self._learning.remember(
            "fix", signature, {"summary": summary, **remedy}, source="ledger",
            confidence=0.7,
        )

    async def recent(self, limit: int = 10) -> list[dict]:
        rows = await self._store.fetchall(
            "SELECT * FROM core_ledger ORDER BY last_seen DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    async def _send(self, text: str) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(text)
        except Exception:
            logger.exception("Ledger could not deliver a notification")


def guarded(ledger: Ledger, source: str):
    """Decorator: run the wrapped coroutine, route failures to the ledger."""
    def wrap(fn):
        async def inner(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                await ledger.record(e, source)
                return None
        inner.__name__ = getattr(fn, "__name__", source)
        return inner
    return wrap
