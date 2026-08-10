"""Command handlers for health plugin."""
from __future__ import annotations

from typing import Any

from pa.plugins import AppContext

VALID_CATEGORIES = {"exercise", "sleep", "water", "weight", "mood", "steps"}


async def handle_log(ctx: AppContext, update: Any, context: Any) -> str:
    """Log a health entry: /log <category> <value> [unit] [notes]"""
    args = context.args if context.args else []
    if len(args) < 2:
        return (
            "Usage: /log <category> <value> [unit] [notes]\n"
            "Examples:\n"
            "  /log exercise 3 miles running\n"
            "  /log sleep 7 hours\n"
            "  /log weight 185\n"
            "  /log mood 7\n"
            "  /log water 8 glasses\n"
            "  /log steps 10000"
        )

    category = args[0].lower()
    if category not in VALID_CATEGORIES:
        return f"Unknown category '{category}'. Valid: {', '.join(sorted(VALID_CATEGORIES))}"

    try:
        value = float(args[1])
    except ValueError:
        return f"Value must be a number, got '{args[1]}'."

    unit = None
    notes = None
    if len(args) >= 3:
        # If arg 3 looks like a unit (single word, not too long), treat as unit
        if len(args[2]) <= 15 and not args[2].replace("'", "").replace("-", "").isdigit():
            unit = args[2]
            if len(args) >= 4:
                notes = " ".join(args[3:])
        else:
            notes = " ".join(args[2:])

    await ctx.store.execute(
        "INSERT INTO health_logs (category, value, unit, notes) VALUES (?, ?, ?, ?)",
        (category, value, unit, notes),
    )

    # Check goal progress
    from pa.plugins.health.nl import _goal_progress
    progress = await _goal_progress(ctx, category, value, unit)

    unit_str = f" {unit}" if unit else ""
    response = f"Logged {value}{unit_str} of {category}."
    if notes:
        response += f" ({notes})"
    if progress:
        response += f"\n{progress}"
    return response


async def handle_health(ctx: AppContext, update: Any, context: Any) -> str:
    """Show this week's health summary with streaks."""
    # Get this week's logs
    logs = await ctx.store.fetchall(
        """SELECT category, SUM(value) AS total, unit, COUNT(*) AS entries
           FROM health_logs
           WHERE logged_at >= date('now', 'weekday 1', '-7 days')
           GROUP BY category
           ORDER BY category""",
    )

    if not logs:
        return "No health data logged this week. Use /log or just tell me about your activity!"

    # Get goals
    goals = await ctx.store.fetchall("SELECT * FROM health_goals")
    goal_map = {g["category"]: g for g in goals}

    lines = ["**This Week's Health Summary**\n"]
    for log in logs:
        cat = log["category"]
        total = log["total"]
        unit = log["unit"] or ""
        entries = log["entries"]

        line = f"  {cat.capitalize()}: {total} {unit} ({entries} entries)"

        goal = goal_map.get(cat)
        if goal:
            target = goal["target"]
            g_unit = goal.get("unit") or unit
            freq = goal.get("frequency", "daily")
            if freq == "daily":
                # Daily goal: compare average
                avg = total / max(entries, 1)
                pct = min(100, int(avg / target * 100)) if target else 0
                line += f" — avg {avg:.1f}/{target} {g_unit}/day ({pct}%)"
            else:
                pct = min(100, int(total / target * 100)) if target else 0
                line += f" — {total}/{target} {g_unit} ({pct}%)"

        lines.append(line)

    # Streaks: count consecutive days with any log
    streak = await _calculate_streak(ctx)
    if streak > 1:
        lines.append(f"\nStreak: {streak} days in a row!")
    elif streak == 1:
        lines.append("\nStreak: 1 day — keep it going!")

    return "\n".join(lines)


async def handle_goal(ctx: AppContext, update: Any, context: Any) -> str:
    """Set a health goal: /goal <category> <target> [unit]"""
    args = context.args if context.args else []
    if len(args) < 2:
        return (
            "Usage: /goal <category> <target> [unit]\n"
            "Examples:\n"
            "  /goal exercise 3 miles\n"
            "  /goal sleep 7 hours\n"
            "  /goal water 8 glasses\n"
            "  /goal steps 10000"
        )

    category = args[0].lower()
    if category not in VALID_CATEGORIES:
        return f"Unknown category '{category}'. Valid: {', '.join(sorted(VALID_CATEGORIES))}"

    try:
        target = float(args[1])
    except ValueError:
        return f"Target must be a number, got '{args[1]}'."

    unit = args[2] if len(args) >= 3 else None

    # Upsert goal
    existing = await ctx.store.fetchone(
        "SELECT id FROM health_goals WHERE category = ?", (category,)
    )
    if existing:
        await ctx.store.execute(
            "UPDATE health_goals SET target = ?, unit = ? WHERE category = ?",
            (target, unit, category),
        )
        verb = "Updated"
    else:
        await ctx.store.execute(
            "INSERT INTO health_goals (category, target, unit) VALUES (?, ?, ?)",
            (category, target, unit),
        )
        verb = "Set"

    unit_str = f" {unit}" if unit else ""
    return f"{verb} goal: {category} — {target}{unit_str} per day."


async def _calculate_streak(ctx: AppContext) -> int:
    """Count consecutive days with at least one health log entry."""
    rows = await ctx.store.fetchall(
        """SELECT DISTINCT date(logged_at) AS log_date
           FROM health_logs
           ORDER BY log_date DESC
           LIMIT 90""",
    )
    if not rows:
        return 0

    from datetime import date, timedelta
    dates = []
    for r in rows:
        try:
            dates.append(date.fromisoformat(r["log_date"]))
        except (ValueError, TypeError):
            continue

    if not dates:
        return 0

    today = date.today()
    # Streak must include today or yesterday
    if dates[0] < today - timedelta(days=1):
        return 0

    streak = 1
    for i in range(1, len(dates)):
        if dates[i - 1] - dates[i] == timedelta(days=1):
            streak += 1
        else:
            break

    return streak
