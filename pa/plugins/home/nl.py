"""Natural language handlers for the Home Maintenance Tracker plugin."""
import datetime
import json
import re

from telegram import Update

from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_home_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Handle natural language about home maintenance tasks."""
    lower = text.lower().strip()

    # --- "when did I last..." queries ---
    if "when did i" in lower or "last time i" in lower:
        return await _handle_query(ctx, text)

    # --- "I changed the..." / "I replaced the..." / action phrases ---
    action_patterns = [
        "changed the", "replaced the", "serviced the", "cleaned the", "mowed the",
    ]
    if any(p in lower for p in action_patterns):
        return await _handle_done(ctx, text)

    # --- Fall back to keyword match: check if it's about a known task ---
    return await _handle_query(ctx, text)


async def _handle_query(ctx: AppContext, text: str) -> str:
    """Look up when a maintenance task was last done."""
    task_name = await _parse_task_name(ctx, text)
    if not task_name:
        return await _fuzzy_search(ctx, text)

    task = await ctx.store.fetchone(
        "SELECT name, last_done, next_due, frequency_days FROM home_tasks WHERE name = ?",
        (task_name,),
    )
    if not task:
        return await _fuzzy_search(ctx, text)

    display = task["name"].replace("_", " ").title()
    if task["last_done"]:
        last = task["last_done"]
        days_ago = (datetime.date.today() - datetime.date.fromisoformat(last)).days
        next_due = task["next_due"] or "unknown"
        return f"**{display}** was last done {last} ({days_ago} days ago). Next due: {next_due}."
    else:
        return f"**{display}** has never been marked as done. It's tracked every {task['frequency_days']} days."


async def _handle_done(ctx: AppContext, text: str) -> str:
    """Mark a task as done based on natural language."""
    task_name = await _parse_task_name(ctx, text)
    if not task_name:
        return "I couldn't figure out which maintenance task you mean. Use /home to see your tasks."

    task = await ctx.store.fetchone(
        "SELECT id, name, frequency_days FROM home_tasks WHERE name = ?",
        (task_name,),
    )
    if not task:
        return (
            f"I don't have a task called '{task_name}'. "
            f"Add it first with /home_add {task_name} <days>"
        )

    today = datetime.date.today().isoformat()
    next_due = (datetime.date.today() + datetime.timedelta(days=task["frequency_days"])).isoformat()

    await ctx.store.execute(
        "UPDATE home_tasks SET last_done = ?, next_due = ? WHERE id = ?",
        (today, next_due, task["id"]),
    )
    await ctx.store.execute(
        "INSERT INTO home_log (task_name, done_at) VALUES (?, ?)",
        (task["name"], today),
    )

    display = task["name"].replace("_", " ").title()
    return f"Logged: **{display}** done today. Next due {next_due}."


async def _parse_task_name(ctx: AppContext, text: str) -> str | None:
    """Use Haiku to extract the task name from natural language, matching against known tasks."""
    all_tasks = await ctx.store.fetchall("SELECT name FROM home_tasks")
    if not all_tasks:
        return None

    task_names = [t["name"] for t in all_tasks]

    system = (
        "You are a parser. The user said something about a home maintenance task. "
        "Match it to one of these known tasks and return ONLY the exact task name. "
        "If no match, return NONE.\n\n"
        f"Known tasks: {', '.join(task_names)}"
    )

    try:
        result = await ctx.brain.query(
            text, system_prompt=system,
            tier=Tier.FAST, use_conversation=False,
        )
        result = result.strip().lower()
        if result in task_names:
            return result
        # Try partial match
        for tn in task_names:
            if tn in result or result in tn:
                return tn
    except Exception:
        pass

    return None


async def _fuzzy_search(ctx: AppContext, text: str) -> str:
    """Try to find a matching task by keyword when exact parse fails."""
    all_tasks = await ctx.store.fetchall(
        "SELECT name, last_done, next_due, frequency_days FROM home_tasks"
    )
    if not all_tasks:
        return "No home maintenance tasks tracked yet. Use /home_add to create one."

    lower = text.lower()
    for task in all_tasks:
        # Check if any word from the task name appears in the message
        task_words = task["name"].replace("_", " ").split()
        if any(w in lower for w in task_words if len(w) > 3):
            display = task["name"].replace("_", " ").title()
            if task["last_done"]:
                days_ago = (datetime.date.today() - datetime.date.fromisoformat(task["last_done"])).days
                return f"**{display}** was last done {task['last_done']} ({days_ago} days ago). Next due: {task['next_due']}."
            else:
                return f"**{display}** is tracked (every {task['frequency_days']}d) but has never been marked done."

    task_list = ", ".join(t["name"] for t in all_tasks)
    return f"I couldn't match that to a tracked task. Your tasks: {task_list}"
