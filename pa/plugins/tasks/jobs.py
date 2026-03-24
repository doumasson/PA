"""Scheduled jobs for the tasks plugin."""
from __future__ import annotations

import datetime

from pa.plugins import Job


async def job_task_reminders(ctx) -> None:
    """Daily at 7:15am — list today's tasks and overdue tasks."""
    today = datetime.date.today().isoformat()

    # Today's tasks
    todays = await ctx.store.fetchall(
        """SELECT id, title, due_time, priority
           FROM tasks_items
           WHERE status = 'pending' AND due_date = ?
           ORDER BY
             CASE WHEN due_time IS NULL THEN 1 ELSE 0 END,
             due_time ASC""",
        (today,),
    )

    # Overdue tasks
    overdue = await ctx.store.fetchall(
        """SELECT id, title, due_date, due_time, priority
           FROM tasks_items
           WHERE status = 'pending' AND due_date < ?
           ORDER BY due_date ASC""",
        (today,),
    )

    if not todays and not overdue:
        return  # Nothing to report

    lines = []

    if overdue:
        lines.append("OVERDUE:")
        for r in overdue:
            pri = f" [{r['priority'].upper()}]" if r["priority"] != "normal" else ""
            time_str = f" at {r['due_time']}" if r["due_time"] else ""
            lines.append(f"  {r['id']}. {r['title']} — was due {r['due_date']}{time_str}{pri}")
        lines.append("")

    if todays:
        lines.append("Today's tasks:")
        for r in todays:
            pri = f" [{r['priority'].upper()}]" if r["priority"] != "normal" else ""
            time_str = f" at {r['due_time']}" if r["due_time"] else ""
            lines.append(f"  {r['id']}. {r['title']}{time_str}{pri}")

    await ctx.bot.send_message("\n".join(lines))


def get_task_jobs() -> list[Job]:
    """Return scheduled jobs for the tasks plugin."""
    return [
        Job(
            name="task_reminders",
            handler=job_task_reminders,
            trigger="cron",
            kwargs={"hour": 7, "minute": 15},
        ),
    ]
