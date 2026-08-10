"""Natural language handler for the tasks plugin."""
from __future__ import annotations

import datetime

from telegram import Update

from pa.plugins import AppContext
from pa.core.brain import Tier

_DAY_MAP = {"monday": "mon", "tuesday": "tue", "wednesday": "wed",
            "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun"}


def _recurring_trigger(recurring, hour, minute, recurring_day, due_date):
    """Map a cadence to a scheduler (trigger, kwargs). Without this, monthly
    and biweekly reminders fell through to {hour, minute} and fired DAILY."""
    if recurring == "weekly":
        return "cron", {"hour": hour, "minute": minute,
                        "day_of_week": _DAY_MAP.get((recurring_day or "").lower(), "mon")}
    if recurring == "monthly":
        day = 1
        if due_date:
            try:
                day = datetime.date.fromisoformat(due_date).day
            except ValueError:
                pass
        return "cron", {"hour": hour, "minute": minute, "day": day}
    if recurring == "biweekly":
        # Cron can't express "every 2 weeks"; use a 14-day interval.
        return "interval", {"hours": 24 * 14}
    return "cron", {"hour": hour, "minute": minute}  # daily


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

    title = text
    due_date = None
    due_time = None
    priority = "normal"
    recurring = None
    recurring_day = None
    recurring_time = "08:00"

    try:
        data = await ctx.brain.query_json(text, tier=Tier.PARSE, system=system)
        title = data.get("title", text)
        due_date = data.get("due_date") or None
        due_time = data.get("due_time") or None
        p = data.get("priority", "normal")
        priority = p if p in ("low", "normal", "high", "urgent") else "normal"
        recurring = data.get("recurring") or None
        recurring_day = data.get("recurring_day") or None
        recurring_time = data.get("recurring_time") or "08:00"
    except ValueError:
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

        trigger, kwargs = _recurring_trigger(
            recurring, hour, minute, recurring_day, due_date
        )
        try:
            await ctx.scheduler.add_dynamic_job(
                job_name, _recurring_alert, trigger, kwargs
            )
        except Exception as e:
            if ctx.ledger:
                await ctx.ledger.record(e, source="tasks.recurring_register")

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


# Words that appear in close-request phrasing itself and prove nothing about
# WHICH task the user means — they don't count as referring to a title.
_TRIVIAL_WORDS = frozenset({
    "the", "a", "an", "it", "of", "and", "or", "to", "my", "that", "this",
    "task", "tasks", "reminder", "todo", "get", "rid", "kill", "cancel",
    "delete", "remove", "done", "with", "finished", "already", "did", "no",
    "longer", "need", "not", "relevant", "anymore", "mark", "about", "i",
    "im", "is", "was", "please", "you", "your",
})


def _title_tokens(text: str) -> set[str]:
    import re
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _TRIVIAL_WORDS}


def _refers_to(text: str, row) -> bool:
    """The user's own words must touch the task — a shared title word or an
    explicit number. An LLM match without this is a substitution, not a match."""
    import re
    if _title_tokens(text) & _title_tokens(row["title"]):
        return True
    return bool(re.search(rf"(?:#|\bnumber |\btask )({row['id']})\b", text.lower()))


async def _already_closed_matches(ctx: AppContext, text: str) -> str:
    """If the user named a task that's already done/cancelled, say so."""
    closed_rows = await ctx.store.fetchall(
        "SELECT id, title, status FROM tasks_items WHERE status != 'pending' "
        "ORDER BY id DESC LIMIT 100"
    )
    matches = [r for r in closed_rows if _refers_to(text, r)]
    return "\n".join(
        f"'{r['title']}' is already {r['status']} — nothing to do." for r in matches
    )


async def handle_task_close_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Close tasks named conversationally: mark done or cancel ("kill") them.

    The pending list is small, so it goes straight into the PARSE prompt —
    the model matches loose references ("the weekly alert thing") against
    real titles instead of us guessing with substring search.
    """
    rows = await ctx.store.fetchall(
        "SELECT id, title, recurring FROM tasks_items WHERE status = 'pending' "
        "ORDER BY id LIMIT 50"
    )
    if not rows:
        already = await _already_closed_matches(ctx, text)
        if already:
            return already
        return "There are no pending tasks to close."

    task_lines = "\n".join(f"- id {r['id']}: {r['title']}" for r in rows)
    system = (
        "The user wants to close some of their pending tasks. Match what they "
        "said against this list:\n" + task_lines + "\n\n"
        'Return ONLY raw JSON: {"close": [{"id": <task id>, "status": '
        '"done"|"cancelled"}]}\n'
        '- "done" if they finished it; "cancelled" if they want it killed / '
        "no longer relevant\n"
        "- Only include tasks the user clearly referred to. NEVER substitute a "
        "different task for one they named — if what they named is not in the "
        'list, return {"close": []}'
    )

    to_close: list[dict] = []
    try:
        data = await ctx.brain.query_json(text, tier=Tier.PARSE, system=system)
        by_id = {r["id"]: r for r in rows}
        for item in data.get("close", []):
            row = by_id.get(item.get("id"))
            if row is not None and _refers_to(text, row):
                status = item.get("status")
                to_close.append({
                    "row": row,
                    "status": status if status in ("done", "cancelled") else "done",
                })
    except ValueError:
        pass

    if not to_close:
        # Maybe they named a task that's already closed — answer that
        # directly instead of pointing at an unrelated pending list.
        already = await _already_closed_matches(ctx, text)
        if already:
            return already
        return (
            "I couldn't match that to a pending task. Here's what's open:\n"
            + "\n".join(f"  {r['id']}. {r['title']}" for r in rows)
            + "\n\nTell me which one, or use /done or /cancel with the number."
        )

    closed = []
    for item in to_close:
        row, status = item["row"], item["status"]
        await ctx.store.execute(
            "UPDATE tasks_items SET status = ?, "
            "completed_at = CASE WHEN ? = 'done' THEN CURRENT_TIMESTAMP END "
            "WHERE id = ?",
            (status, status, row["id"]),
        )
        if row["recurring"] and ctx.scheduler:
            try:
                await ctx.scheduler.remove_dynamic_job(f"recurring_task_{row['id']}")
            except Exception:
                pass  # job may not exist on this boot; the DB status is what matters
        verb = "Done" if status == "done" else "Killed"
        closed.append(f"{verb}: {row['title']} (#{row['id']})")
    return "\n".join(closed)


async def handle_task_list_nl(ctx: AppContext, text: str, update: Update) -> str:
    """List pending tasks, flagging overdue ones."""
    rows = await ctx.store.fetchall(
        """SELECT id, title, due_date, due_time, priority FROM tasks_items
           WHERE status = 'pending'
           ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC"""
    )
    if not rows:
        return "Nothing pending. Use /todo or just tell me to remind you of something."
    today = datetime.date.today().isoformat()
    lines = ["Pending tasks:"]
    for r in rows:
        due = ""
        if r["due_date"]:
            overdue = " ⚠️ OVERDUE" if r["due_date"] < today else ""
            due = f" — due {r['due_date']}{overdue}"
        pri = f" [{r['priority'].upper()}]" if r["priority"] not in (None, "normal") else ""
        lines.append(f"  {r['id']}. {r['title']}{due}{pri}")
    return "\n".join(lines)
