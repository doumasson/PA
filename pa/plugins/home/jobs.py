"""Scheduled jobs for the Home Maintenance Tracker plugin."""
import datetime


async def job_home_reminders(ctx) -> None:
    """Monday 8:45am — check for overdue or due-this-week home tasks and alert."""
    today = datetime.date.today()
    week_out = (today + datetime.timedelta(days=7)).isoformat()

    tasks = await ctx.store.fetchall(
        "SELECT name, frequency_days, last_done, next_due, notes "
        "FROM home_tasks WHERE next_due IS NOT NULL AND next_due <= ? "
        "ORDER BY next_due ASC",
        (week_out,),
    )

    # Also grab tasks that have never been done
    never_done = await ctx.store.fetchall(
        "SELECT name, frequency_days, notes "
        "FROM home_tasks WHERE last_done IS NULL"
    )

    if not tasks and not never_done:
        return  # Nothing to report

    lines = ["\U0001f3e0 **Home Maintenance Reminder**\n"]

    for t in tasks:
        display = t["name"].replace("_", " ").title()
        due_date = datetime.date.fromisoformat(t["next_due"])
        days_left = (due_date - today).days
        notes = f" ({t['notes']})" if t["notes"] else ""

        if days_left < 0:
            lines.append(f"\U0001f534 **{display}** — OVERDUE by {abs(days_left)} days{notes}")
        else:
            lines.append(f"\U0001f7e1 **{display}** — due in {days_left} days{notes}")

    for t in never_done:
        display = t["name"].replace("_", " ").title()
        notes = f" ({t['notes']})" if t["notes"] else ""
        lines.append(f"\U0001f7e1 **{display}** — never done, tracked every {t['frequency_days']}d{notes}")

    message = "\n".join(lines)
    try:
        await ctx.bot.send_message(message)
    except Exception:
        pass
