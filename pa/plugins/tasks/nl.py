"""Natural language handler for the tasks plugin."""
from __future__ import annotations

import json
import datetime

from telegram import Update

from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_task_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Parse a natural language task request and save it."""
    SYSTEM = """Parse this message into a task. Extract:
- title: the task itself (short, action-oriented)
- due_date: ISO date (YYYY-MM-DD) if mentioned, else null
- due_time: HH:MM (24h) if mentioned, else null
- priority: low/normal/high/urgent based on language, default normal

Today is {today}. "Monday" means next Monday, "tomorrow" means tomorrow, etc.
Return ONLY raw JSON: {{"title":"...","due_date":"...","due_time":"...","priority":"..."}}"""

    today = datetime.date.today().isoformat()
    system = SYSTEM.replace("{today}", today)

    result = await ctx.brain.query(text, system_prompt=system, tier=Tier.FAST, use_conversation=False)

    title = text
    due_date = None
    due_time = None
    priority = "normal"

    try:
        start = result.find("{")
        end = result.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(result[start : end + 1])
            title = data.get("title", text)
            due_date = data.get("due_date") or None
            due_time = data.get("due_time") or None
            p = data.get("priority", "normal")
            priority = p if p in ("low", "normal", "high", "urgent") else "normal"
    except (json.JSONDecodeError, KeyError):
        pass

    task_id = await ctx.store.execute(
        """INSERT INTO tasks_items (title, due_date, due_time, priority)
           VALUES (?, ?, ?, ?)""",
        (title, due_date, due_time, priority),
    )

    msg = f"Added: {title}"
    due_parts = []
    if due_date:
        due_parts.append(due_date)
    if due_time:
        due_parts.append(f"at {due_time}")
    if due_parts:
        msg += f" — due {' '.join(due_parts)}"
    if priority != "normal":
        msg += f" [{priority.upper()}]"
    msg += f" (#{task_id})"
    return msg
