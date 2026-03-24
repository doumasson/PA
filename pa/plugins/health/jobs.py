"""Scheduled jobs for health plugin."""
from __future__ import annotations

import logging

from pa.plugins import Job

log = logging.getLogger(__name__)


async def job_health_weekly(ctx) -> None:
    """Sunday 7:30am — send weekly health summary with goal comparisons."""
    logs = await ctx.store.fetchall(
        """SELECT category, SUM(value) AS total, unit, COUNT(*) AS entries,
                  AVG(value) AS avg_val, MIN(value) AS min_val, MAX(value) AS max_val
           FROM health_logs
           WHERE logged_at >= date('now', '-7 days')
           GROUP BY category
           ORDER BY category""",
    )

    if not logs:
        return  # Nothing to report

    goals = await ctx.store.fetchall("SELECT * FROM health_goals")
    goal_map = {g["category"]: g for g in goals}

    lines = ["Weekly Health Report\n"]

    for entry in logs:
        cat = entry["category"]
        total = entry["total"]
        avg = entry["avg_val"]
        unit = entry["unit"] or ""
        entries = entry["entries"]

        line = f"  {cat.capitalize()}: {total} {unit} total"

        if cat == "sleep":
            line += f" (avg {avg:.1f} {unit}/night)"
        elif cat == "weight":
            line += f" (latest range {entry['min_val']}-{entry['max_val']} {unit})"
        elif cat == "mood":
            line += f" (avg {avg:.1f}/10)"
        elif cat in ("exercise", "steps", "water"):
            line += f" across {entries} sessions"

        goal = goal_map.get(cat)
        if goal:
            target = goal["target"]
            g_unit = goal.get("unit") or unit
            freq = goal.get("frequency", "daily")
            if freq == "daily":
                daily_avg = total / 7
                pct = min(100, int(daily_avg / target * 100)) if target else 0
                status = "met" if pct >= 100 else "missed"
                line += f" — goal: {target} {g_unit}/day, avg: {daily_avg:.1f} ({pct}%, {status})"
            else:
                pct = min(100, int(total / target * 100)) if target else 0
                status = "met" if pct >= 100 else "missed"
                line += f" — goal: {target} {g_unit}/week ({pct}%, {status})"

        lines.append(line)

    # Weight trend
    weight_rows = await ctx.store.fetchall(
        """SELECT value, logged_at FROM health_logs
           WHERE category = 'weight'
             AND logged_at >= date('now', '-14 days')
           ORDER BY logged_at""",
    )
    if len(weight_rows) >= 2:
        first = weight_rows[0]["value"]
        last = weight_rows[-1]["value"]
        diff = last - first
        direction = "up" if diff > 0 else "down" if diff < 0 else "unchanged"
        lines.append(f"\n  Weight trend (2wk): {direction} {abs(diff):.1f} lbs")

    try:
        await ctx.bot.send_message("\n".join(lines))
    except Exception as e:
        log.error("Failed to send weekly health summary: %s", e)


def get_health_jobs() -> list[Job]:
    """Return scheduled jobs for the health plugin."""
    return [
        Job(
            name="health_weekly",
            handler=job_health_weekly,
            trigger="cron",
            kwargs={"day_of_week": "sun", "hour": 7, "minute": 30},
        ),
    ]
