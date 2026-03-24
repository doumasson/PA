"""Command handlers for the tasks plugin."""
from __future__ import annotations

import json
import re
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_todo(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Add a task. Usage: /todo <task> [due date]"""
    raw = " ".join(context.args) if context.args else ""
    if not raw.strip():
        return "Usage: /todo <task description> [due date]\nExamples:\n  /todo Call dentist Monday\n  /todo Pick up Maddox at 4pm 2026-03-25"

    # Use Haiku to parse the task
    parsed = await _parse_task(ctx, raw)
    task_id = await _insert_task(ctx, parsed)
    return _format_added(parsed, task_id)


async def handle_todos(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """List pending tasks sorted by due date."""
    rows = await ctx.store.fetchall(
        """SELECT id, title, due_date, due_time, priority, status
           FROM tasks_items
           WHERE status = 'pending'
           ORDER BY
             CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
             due_date ASC,
             CASE priority
               WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
               WHEN 'normal' THEN 2 WHEN 'low' THEN 3
             END"""
    )
    if not rows:
        return "No pending tasks. Use /todo to add one."

    lines = ["Pending tasks:\n"]
    for r in rows:
        due = ""
        if r["due_date"]:
            due = f" — due {r['due_date']}"
            if r["due_time"]:
                due += f" at {r['due_time']}"
        pri = ""
        if r["priority"] and r["priority"] != "normal":
            pri = f" [{r['priority'].upper()}]"
        lines.append(f"  {r['id']}. {r['title']}{due}{pri}")
    return "\n".join(lines)


async def handle_done(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Mark a task complete by ID or title match."""
    raw = " ".join(context.args) if context.args else ""
    if not raw.strip():
        return "Usage: /done <task id or title>"

    task = await _find_task(ctx, raw)
    if not task:
        return f"No pending task found matching '{raw}'."

    await ctx.store.execute(
        "UPDATE tasks_items SET status = 'done', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (task["id"],),
    )
    return f"Done: {task['title']}"


async def handle_cancel(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Cancel a task by ID."""
    raw = " ".join(context.args) if context.args else ""
    if not raw.strip():
        return "Usage: /cancel <task id>"

    try:
        task_id = int(raw.strip())
    except ValueError:
        return "Usage: /cancel <task id> (use a number)"

    task = await ctx.store.fetchone(
        "SELECT id, title FROM tasks_items WHERE id = ? AND status = 'pending'",
        (task_id,),
    )
    if not task:
        return f"No pending task with ID {task_id}."

    await ctx.store.execute(
        "UPDATE tasks_items SET status = 'cancelled' WHERE id = ?",
        (task_id,),
    )
    return f"Cancelled: {task['title']}"


# ── Helpers ──────────────────────────────────────────────────────────


async def _parse_task(ctx: AppContext, raw: str) -> dict[str, Any]:
    """Use Haiku to extract title, due_date, due_time, priority from raw text."""
    SYSTEM = """Parse this task description. Extract:
- title: the task itself (short, action-oriented)
- due_date: ISO date (YYYY-MM-DD) if mentioned, else null
- due_time: HH:MM (24h) if mentioned, else null
- priority: low/normal/high/urgent based on language, default normal

Today is {today}. "Monday" means next Monday, "tomorrow" means tomorrow, etc.
Return ONLY raw JSON: {{"title":"...","due_date":"...","due_time":"...","priority":"..."}}"""

    import datetime
    today = datetime.date.today().isoformat()
    system = SYSTEM.replace("{today}", today)

    result = await ctx.brain.query(raw, system_prompt=system, tier=Tier.FAST, use_conversation=False)

    try:
        start = result.find("{")
        end = result.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(result[start : end + 1])
            return {
                "title": data.get("title", raw),
                "due_date": data.get("due_date") or None,
                "due_time": data.get("due_time") or None,
                "priority": data.get("priority", "normal") if data.get("priority") in ("low", "normal", "high", "urgent") else "normal",
            }
    except (json.JSONDecodeError, KeyError):
        pass

    # Fallback: use raw text as title
    return {"title": raw, "due_date": None, "due_time": None, "priority": "normal"}


async def _insert_task(ctx: AppContext, parsed: dict[str, Any]) -> int:
    """Insert a task and return its ID."""
    return await ctx.store.execute(
        """INSERT INTO tasks_items (title, due_date, due_time, priority)
           VALUES (?, ?, ?, ?)""",
        (parsed["title"], parsed["due_date"], parsed["due_time"], parsed["priority"]),
    )


async def _find_task(ctx: AppContext, query: str) -> dict[str, Any] | None:
    """Find a pending task by ID or title substring."""
    # Try as ID first
    try:
        task_id = int(query.strip())
        return await ctx.store.fetchone(
            "SELECT id, title FROM tasks_items WHERE id = ? AND status = 'pending'",
            (task_id,),
        )
    except ValueError:
        pass

    # Fuzzy title match
    return await ctx.store.fetchone(
        "SELECT id, title FROM tasks_items WHERE status = 'pending' AND title LIKE ? LIMIT 1",
        (f"%{query.strip()}%",),
    )


def _format_added(parsed: dict[str, Any], task_id: int) -> str:
    """Format the confirmation message for a newly added task."""
    msg = f"Added: {parsed['title']}"
    due_parts = []
    if parsed["due_date"]:
        due_parts.append(parsed["due_date"])
    if parsed["due_time"]:
        due_parts.append(f"at {parsed['due_time']}")
    if due_parts:
        msg += f" — due {' '.join(due_parts)}"
    if parsed["priority"] != "normal":
        msg += f" [{parsed['priority'].upper()}]"
    msg += f" (#{task_id})"
    return msg
