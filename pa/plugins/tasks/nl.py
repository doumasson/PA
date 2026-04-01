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
- recurring: "daily"|"weekly"|"biweekly"|"monthly"|null if they want it repeated
- recurring_day: day of week if weekly (e.g. "monday"), else null
- recurring_time: HH:MM if they specify a time for the recurring alert, else "08:00"

Today is {today}. "Monday" means next Monday, "tomorrow" means tomorrow, etc.
"track weekly" or "alert me every week" means recurring=weekly.
"remind me every day" means recurring=daily.

Return ONLY raw JSON: {{"title":"...","due_date":"...","due_time":"...","priority":"...","recurring":"...","recurring_day":"...","recurring_time":"..."}}"""

    today = datetime.date.today().isoformat()
    system = SYSTEM.replace("{today}", today)

    result = await ctx.brain.query(text, system_prompt=system, tier=Tier.FAST, use_conversation=False)

    title = text
    due_date = None
    due_time = None
    priority = "normal"
    recurring = None
    recurring_day = None
    recurring_time = "08:00"

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
            recurring = data.get("recurring") or None
            recurring_day = data.get("recurring_day") or None
            recurring_time = data.get("recurring_time") or "08:00"
    except (json.JSONDecodeError, KeyError):
        pass

    # Set due_date for recurring tasks if not specified
    if recurring and not due_date:
        if recurring == "daily":
            due_date = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        elif recurring == "weekly":
            due_date = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        elif recurring == "monthly":
            due_date = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()

    task_id = await ctx.store.execute(
        """INSERT INTO tasks_items (title, due_date, due_time, priority, recurring)
           VALUES (?, ?, ?, ?, ?)""",
        (title, due_date, due_time, priority, recurring),
    )

    # Set up a real recurring job if scheduler is available
    if recurring and ctx.scheduler:
        job_name = f"recurring_task_{task_id}"
        hour, minute = 8, 0
        try:
            parts = recurring_time.split(":")
            hour, minute = int(parts[0]), int(parts[1])
        except Exception:
            pass

        async def _recurring_alert(_ctx, _title=title, _task_id=task_id):
            await _ctx.bot.send_message(f"⏰ Recurring reminder: {_title} (#{_task_id})")

        kwargs = {"hour": hour, "minute": minute}
        if recurring == "weekly" and recurring_day:
            _day_map = {"monday": "mon", "tuesday": "tue", "wednesday": "wed",
                        "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun"}
            kwargs["day_of_week"] = _day_map.get(recurring_day.lower(), "mon")

        try:
            await ctx.scheduler.add_dynamic_job(job_name, _recurring_alert, "cron", kwargs)
        except Exception:
            pass  # Scheduler might not be started yet

    msg = f"Added: {title}"
    due_parts = []
    if due_date:
        due_parts.append(due_date)
    if due_time:
        due_parts.append(f"at {due_time}")
    if due_parts:
        msg += f" — due {' '.join(due_parts)}"
    if recurring:
        msg += f" [recurring {recurring}]"
    if priority != "normal":
        msg += f" [{priority.upper()}]"
    msg += f" (#{task_id})"
    return msg
