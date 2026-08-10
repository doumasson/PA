"""Reflex-rate and LLM usage stats — the measurable 'getting smarter' gauge."""
from __future__ import annotations

import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS core_stats (
    day TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, metric)
);
"""

# Metrics:
#   handled_l0 / handled_l1 / handled_l2   message routing outcomes
#   llm_calls.<backend>.<tier>             completions per backend/tier
#   llm_tokens_in / llm_tokens_out         token volume (all backends)
#   llm_errors                             failed completions after retries
#   learnings_created                      artifacts deposited


class Stats:
    def __init__(self, store):
        self._store = store

    def schema_sql(self) -> str:
        return SCHEMA

    async def bump(self, metric: str, value: float = 1.0) -> None:
        day = datetime.date.today().isoformat()
        await self._store.execute(
            "INSERT INTO core_stats (day, metric, value) VALUES (?, ?, ?) "
            "ON CONFLICT(day, metric) DO UPDATE SET value = value + excluded.value",
            (day, metric, value),
        )

    async def window(self, days: int) -> dict[str, float]:
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        rows = await self._store.fetchall(
            "SELECT metric, SUM(value) AS total FROM core_stats "
            "WHERE day >= ? GROUP BY metric",
            (since,),
        )
        return {r["metric"]: r["total"] for r in rows}

    async def reflex_report(self) -> str:
        """Render the /stats view: this week vs last, reflex rate front and center."""
        this_week = await self.window(7)
        prior = await self.window(14)
        last_week = {k: prior.get(k, 0) - this_week.get(k, 0) for k in prior}

        def rate(w: dict[str, float]) -> tuple[float, float]:
            l0 = w.get("handled_l0", 0)
            total = l0 + w.get("handled_l1", 0) + w.get("handled_l2", 0)
            return (l0 / total * 100 if total else 0.0, total)

        r_now, n_now = rate(this_week)
        r_prev, n_prev = rate(last_week)
        trend = "→"
        if r_now > r_prev + 1:
            trend = "↑"
        elif r_now < r_prev - 1:
            trend = "↓"

        lines = [
            "**Albus Stats**",
            f"Reflex rate (handled free): {r_now:.0f}% of {n_now:.0f} requests this week "
            f"({trend} vs {r_prev:.0f}% last week)",
            f"LLM calls: parse {this_week.get('handled_l1', 0):.0f}, "
            f"reason {this_week.get('handled_l2', 0):.0f}, "
            f"errors {this_week.get('llm_errors', 0):.0f}",
            f"Learnings created this week: {this_week.get('learnings_created', 0):.0f}",
        ]
        backend_lines = [
            f"  {m.removeprefix('llm_calls.')}: {v:.0f}"
            for m, v in sorted(this_week.items())
            if m.startswith("llm_calls.")
        ]
        if backend_lines:
            lines.append("By backend/tier:")
            lines.extend(backend_lines)
        return "\n".join(lines)
