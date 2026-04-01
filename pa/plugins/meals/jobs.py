"""Scheduled jobs for the meals plugin."""
from __future__ import annotations

import datetime

from pa.plugins import Job

_STATE_KEY_IGNORED = "dinner_nag_ignored"
_STATE_KEY_ENGAGED = "dinner_nag_last_engaged"


async def _get_nag_count(ctx) -> int:
    """Get the number of consecutive ignored dinner nags."""
    row = await ctx.store.fetchone(
        "SELECT value FROM google_state WHERE key = ?", (_STATE_KEY_IGNORED,)
    )
    return int(row['value']) if row else 0


async def _increment_nag(ctx) -> None:
    """Increment the ignored dinner nag counter."""
    await ctx.store.execute(
        "INSERT INTO google_state (key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)",
        (_STATE_KEY_IGNORED,),
    )


async def reset_dinner_nag(ctx) -> None:
    """Reset nag counter when user engages with meals. Call from commands/NL handlers."""
    await ctx.store.execute(
        "INSERT INTO google_state (key, value) VALUES (?, '0') "
        "ON CONFLICT(key) DO UPDATE SET value = '0'",
        (_STATE_KEY_IGNORED,),
    )
    await ctx.store.execute(
        "INSERT INTO google_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_STATE_KEY_ENGAGED, datetime.datetime.now().isoformat()),
    )


async def job_meal_reminder(ctx) -> None:
    """Daily at 4pm: Remind about tonight's dinner or suggest planning.

    Backs off after 3 consecutive ignores — switches to Sunday-only until user re-engages.
    """
    today = datetime.date.today()

    # Check backoff: if 3+ ignored, only nag on Sunday
    ignored_count = await _get_nag_count(ctx)
    if ignored_count >= 3 and today.weekday() != 6:  # 6 = Sunday
        return

    row = await ctx.store.fetchone(
        "SELECT * FROM meals_plan WHERE date = ? AND meal_type = 'dinner'",
        (today.isoformat(),),
    )

    try:
        if row:
            notes = f" ({row['notes']})" if row.get("notes") else ""
            await ctx.bot.send_message(f"Tonight's dinner: {row['description']}{notes}")
        else:
            await ctx.bot.send_message("No dinner planned tonight. Want to plan something?")
            await _increment_nag(ctx)
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
