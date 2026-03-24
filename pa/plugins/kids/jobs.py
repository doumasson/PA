"""Scheduled jobs for the kids plugin."""
from __future__ import annotations

import datetime

from pa.plugins import Job


async def job_kids_morning(ctx) -> None:
    """Daily 6:45am: Notify if either kid has events today."""
    today = datetime.date.today().isoformat()
    events = await ctx.store.fetchall(
        "SELECT * FROM kids_events WHERE date = ? ORDER BY time",
        (today,),
    )
    if not events:
        return  # No events today, stay silent

    lines = ["Today for the boys:"]
    for e in events:
        kid = e["kid"].capitalize()
        time_str = f" {e['time']}" if e["time"] else ""
        loc = f" at {e['location']}" if e["location"] else ""
        lines.append(f"• {kid}: {e['title']}{time_str}{loc}")

    try:
        await ctx.bot.send_message("\n".join(lines))
    except Exception:
        pass


def get_kids_jobs() -> list[Job]:
    return [
        Job(
            name="kids_morning",
            handler=job_kids_morning,
            trigger="cron",
            kwargs={"hour": 6, "minute": 45},
        ),
    ]
