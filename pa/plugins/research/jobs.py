"""Scheduled jobs for the research plugin."""
from __future__ import annotations

import logging
from datetime import datetime
from pa.core.tier import Tier
from pa.plugins import Job

log = logging.getLogger(__name__)

WATCHLIST_SYSTEM = """You are a research update assistant. The user is tracking a topic.
Given the topic and the previous summary (if any), provide a brief update covering:
1. What has changed or developed recently
2. Any notable news or events
3. Key takeaways

If nothing significant has changed, say so briefly.
Keep it concise — 100-200 words. Focus on what's NEW."""


async def job_watchlist_update(ctx) -> None:
    """Check watchlist topics for updates (Wed + Sat at 10am)."""
    topics = await ctx.store.fetchall(
        "SELECT id, topic, last_summary FROM research_watchlist ORDER BY id"
    )
    if not topics:
        return

    updates = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for row in topics:
        topic = row["topic"]
        prev = row["last_summary"] or "No previous summary."
        try:
            prompt = (
                f"Topic: {topic}\n\n"
                f"Previous summary: {prev}\n\n"
                f"Provide an update on this topic. What's new or changed?"
            )
            result = await ctx.brain.query(
                prompt,
                system_prompt=WATCHLIST_SYSTEM,
                tier=Tier.STANDARD,
                use_conversation=False,
            )

            await ctx.store.execute(
                "UPDATE research_watchlist SET last_checked = ?, last_summary = ? WHERE id = ?",
                (now, result[:2000], row["id"]),
            )

            # Also log to research_queries for history
            await ctx.store.execute(
                "INSERT INTO research_queries (query, summary) VALUES (?, ?)",
                (f"[watchlist] {topic}", result[:2000]),
            )

            # Only notify if there's something substantive
            no_change_phrases = [
                "nothing significant", "no major changes", "no notable",
                "remains the same", "no new developments",
            ]
            if not any(phrase in result.lower() for phrase in no_change_phrases):
                updates.append(f"**{topic}:**\n{result[:500]}")

        except Exception as e:
            log.error("Watchlist update failed for '%s': %s", topic, e, exc_info=True)

    if updates and ctx.bot:
        header = "**Research Watchlist Updates:**\n\n"
        message = header + "\n\n---\n\n".join(updates)
        if len(message) > 4000:
            message = message[:3997] + "..."
        await ctx.bot.send_message(message)


def get_research_jobs() -> list[Job]:
    """Return scheduled jobs for the research plugin."""
    return [
        Job(
            name="watchlist_wed",
            handler=job_watchlist_update,
            trigger="cron",
            kwargs={"day_of_week": "wed", "hour": 10, "minute": 0},
        ),
        Job(
            name="watchlist_sat",
            handler=job_watchlist_update,
            trigger="cron",
            kwargs={"day_of_week": "sat", "hour": 10, "minute": 0},
        ),
    ]
