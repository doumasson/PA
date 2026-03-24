"""Scheduled jobs for the meals plugin."""
from __future__ import annotations

import datetime

from pa.plugins import Job


async def job_meal_reminder(ctx) -> None:
    """Daily at 4pm: Remind about tonight's dinner or suggest planning."""
    today = datetime.date.today().isoformat()
    row = await ctx.store.fetchone(
        "SELECT * FROM meals_plan WHERE date = ? AND meal_type = 'dinner'",
        (today,),
    )

    try:
        if row:
            notes = f" ({row['notes']})" if row.get("notes") else ""
            await ctx.bot.send_message(f"Tonight's dinner: {row['description']}{notes}")
        else:
            await ctx.bot.send_message("No dinner planned tonight. Want to plan something?")
    except Exception:
        pass


def get_meals_jobs() -> list[Job]:
    return [
        Job(
            name="meal_reminder",
            handler=job_meal_reminder,
            trigger="cron",
            kwargs={"hour": 16, "minute": 0},
        ),
    ]
