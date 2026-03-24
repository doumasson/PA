"""Natural language handler for health plugin."""
from __future__ import annotations

import json
import re
from typing import Any

from telegram import Update

from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_health_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Parse natural language health entries via Haiku and log them."""
    PARSE_PROMPT = """Parse this health-related message into structured data. Return ONLY JSON:
{
  "category": "exercise|sleep|water|weight|mood|steps",
  "value": <number>,
  "unit": "<unit or null>",
  "notes": "<brief note or null>"
}

Examples:
- "I ran 3 miles" -> {"category":"exercise","value":3,"unit":"miles","notes":"running"}
- "slept 6 hours" -> {"category":"sleep","value":6,"unit":"hours","notes":null}
- "I weigh 185" -> {"category":"weight","value":185,"unit":"lbs","notes":null}
- "drank 4 glasses of water" -> {"category":"water","value":4,"unit":"glasses","notes":null}
- "went to gym for an hour" -> {"category":"exercise","value":60,"unit":"minutes","notes":"gym"}
- "feeling great today, 8 out of 10" -> {"category":"mood","value":8,"unit":null,"notes":"feeling great"}
- "walked 5000 steps" -> {"category":"steps","value":5000,"unit":"steps","notes":null}

Raw JSON only, no markdown."""

    result = await ctx.brain.query(
        text, system_prompt=PARSE_PROMPT,
        tier=Tier.FAST, use_conversation=False,
    )

    try:
        result = re.sub(r',\s*([}\]])', r'\1', result.strip())
        start = result.find('{')
        end = result.rfind('}')
        if start == -1:
            return "I couldn't parse that as a health entry. Try: 'I ran 3 miles' or '/log exercise 3 miles'."
        data = json.loads(result[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return "I couldn't parse that as a health entry. Try: 'I ran 3 miles' or '/log exercise 3 miles'."

    category = data.get("category")
    value = data.get("value")
    unit = data.get("unit")
    notes = data.get("notes")

    if not category or value is None:
        return "I couldn't parse that as a health entry. Try: 'I ran 3 miles' or '/log exercise 3 miles'."

    # Save to DB
    await ctx.store.execute(
        "INSERT INTO health_logs (category, value, unit, notes) VALUES (?, ?, ?, ?)",
        (category, float(value), unit, notes),
    )

    # Check for goal progress
    progress = await _goal_progress(ctx, category, value, unit)
    unit_str = f" {unit}" if unit else ""
    response = f"Logged {value}{unit_str} of {category}."
    if notes:
        response += f" ({notes})"
    if progress:
        response += f"\n{progress}"
    return response


async def _goal_progress(ctx: AppContext, category: str, value: float, unit: str | None) -> str | None:
    """Check weekly progress against a goal for the given category."""
    goal = await ctx.store.fetchone(
        "SELECT * FROM health_goals WHERE category = ?", (category,)
    )
    if not goal:
        return None

    # Sum this week's entries (Monday to now)
    rows = await ctx.store.fetchall(
        """SELECT COALESCE(SUM(value), 0) AS total FROM health_logs
           WHERE category = ?
             AND logged_at >= date('now', 'weekday 1', '-7 days')""",
        (category,),
    )
    total = rows[0]["total"] if rows else 0.0
    target = goal["target"]
    freq = goal.get("frequency", "daily")

    if freq == "daily":
        # For daily goals, show today's progress
        day_rows = await ctx.store.fetchall(
            """SELECT COALESCE(SUM(value), 0) AS total FROM health_logs
               WHERE category = ?
                 AND date(logged_at) = date('now')""",
            (category,),
        )
        day_total = day_rows[0]["total"] if day_rows else 0.0
        pct = min(100, int(day_total / target * 100)) if target else 0
        g_unit = goal.get("unit") or unit or ""
        return f"Today: {day_total}/{target} {g_unit} ({pct}%)"
    else:
        # Weekly
        pct = min(100, int(total / target * 100)) if target else 0
        g_unit = goal.get("unit") or unit or ""
        return f"This week: {total}/{target} {g_unit} ({pct}%)"
