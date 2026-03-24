"""Command handlers for the Home Maintenance Tracker plugin."""
import datetime

from telegram import Update

from pa.plugins import AppContext


async def handle_home(ctx: AppContext, update: Update, args: list[str]) -> str:
    """List all home maintenance tasks with status indicators."""
    tasks = await ctx.store.fetchall(
        "SELECT name, frequency_days, last_done, next_due, notes "
        "FROM home_tasks ORDER BY next_due ASC"
    )
    if not tasks:
        return "No home maintenance tasks tracked yet. Use /home_add to create one."

    today = datetime.date.today()
    lines = ["**Home Maintenance Tasks**\n"]

    for t in tasks:
        name = t["name"].replace("_", " ").title()
        freq = t["frequency_days"]
        last = t["last_done"] or "never"
        next_due = t["next_due"]
        notes = f" — {t['notes']}" if t["notes"] else ""

        if next_due:
            due_date = datetime.date.fromisoformat(next_due)
            days_left = (due_date - today).days
            if days_left < 0:
                icon = "\U0001f534"  # red circle — overdue
                status = f"OVERDUE by {abs(days_left)}d"
            elif days_left <= 7:
                icon = "\U0001f7e1"  # yellow circle — due soon
                status = f"due in {days_left}d"
            else:
                icon = "\U0001f7e2"  # green circle — OK
                status = f"due in {days_left}d"
        else:
            icon = "\U0001f7e1"  # yellow — never done
            status = "never done"

        lines.append(f"{icon} **{name}** (every {freq}d) — {status}")
        lines.append(f"   Last: {last}{notes}")

    return "\n".join(lines)


async def handle_home_add(ctx: AppContext, update: Update, args: list[str]) -> str:
    """Add a new home maintenance task.

    Usage: /home_add <name> <frequency_days> [notes...]
    """
    if len(args) < 2:
        return "Usage: /home_add <name> <frequency_days> [notes]\nExample: /home_add furnace_filter 90"

    name = args[0].lower()
    try:
        freq = int(args[1])
    except ValueError:
        return "frequency_days must be a number. Example: /home_add furnace_filter 90"

    notes = " ".join(args[2:]) if len(args) > 2 else None

    existing = await ctx.store.fetchone(
        "SELECT id FROM home_tasks WHERE name = ?", (name,)
    )
    if existing:
        return f"Task '{name}' already exists. Use a different name."

    await ctx.store.execute(
        "INSERT INTO home_tasks (name, frequency_days, notes) VALUES (?, ?, ?)",
        (name, freq, notes),
    )
    display = name.replace("_", " ").title()
    return f"Added: **{display}** — every {freq} days" + (f" ({notes})" if notes else "")


async def handle_home_done(ctx: AppContext, update: Update, args: list[str]) -> str:
    """Mark a task as done and calculate next due date.

    Usage: /home_done <name>
    """
    if not args:
        return "Usage: /home_done <task_name>\nExample: /home_done furnace_filter"

    name = args[0].lower()
    task = await ctx.store.fetchone(
        "SELECT id, name, frequency_days FROM home_tasks WHERE name = ?", (name,)
    )
    if not task:
        # Try fuzzy match
        all_tasks = await ctx.store.fetchall("SELECT name FROM home_tasks")
        suggestions = [t["name"] for t in all_tasks if name in t["name"] or t["name"] in name]
        if suggestions:
            return f"Task '{name}' not found. Did you mean: {', '.join(suggestions)}?"
        return f"Task '{name}' not found. Use /home to see all tasks."

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
    return f"Done: **{display}** — next due {next_due}"
