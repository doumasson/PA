"""Builds the weekly review from every domain Albus watches."""
from __future__ import annotations

import datetime
import logging

from pa.core.brain import Tier
from pa.plugins import AppContext

logger = logging.getLogger(__name__)


async def _calendar_section(ctx: AppContext) -> str:
    if not ctx.vault.is_unlocked:
        return "📅 Calendar: vault locked, couldn't check."
    try:
        from pa.plugins.google.calendar import upcoming_events
        from pa.plugins.google.client import calendar_service
        events = upcoming_events(calendar_service(ctx.vault), days=7)
    except Exception as e:
        if ctx.ledger is not None:
            await ctx.ledger.record(e, source="review_calendar")
        return "📅 Calendar: couldn't reach Google Calendar."
    if not events:
        return "📅 Week ahead: calendar is clear."
    lines = [f"  {e['start'][:16].replace('T', ' ')} — {e['summary']}" for e in events[:10]]
    return "📅 Week ahead:\n" + "\n".join(lines)


async def _money_section(ctx: AppContext) -> str:
    today = datetime.date.today()
    cutoff = (today + datetime.timedelta(days=14)).isoformat()
    bills = await ctx.store.fetchall(
        "SELECT name, amount, due_date FROM finance_bills "
        "WHERE paid_this_cycle = 0 AND due_date >= ? AND due_date <= ? "
        "ORDER BY due_date",
        (today.isoformat(), cutoff),
    )
    parts = []
    if bills:
        total = sum(b["amount"] or 0 for b in bills)
        lines = [
            f"  {b['name']}: ${b['amount'] or 0:,.0f} due {b['due_date']}"
            for b in bills
        ]
        parts.append(f"💸 Due in 14 days (${total:,.0f}):\n" + "\n".join(lines))
    else:
        parts.append("💸 No bills due in the next 14 days.")

    month = today.strftime("%Y-%m")
    spent = await ctx.store.fetchone(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM finance_transactions "
        "WHERE amount > 0 AND strftime('%Y-%m', date) = ?",
        (month,),
    )
    budget = await ctx.store.fetchone(
        "SELECT COALESCE(SUM(monthly_limit), 0) AS b FROM finance_budgets"
    )
    if budget and budget["b"] > 0:
        pct = spent["s"] / budget["b"] * 100
        day_pct = today.day / 30 * 100
        pace = "ahead of" if pct > day_pct + 5 else "on" if pct > day_pct - 10 else "under"
        parts.append(
            f"📊 Month: ${spent['s']:,.0f} of ${budget['b']:,.0f} "
            f"({pct:.0f}%) — {pace} pace."
        )
    return "\n\n".join(parts)


async def _tasks_section(ctx: AppContext) -> str:
    today = datetime.date.today().isoformat()
    week = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    overdue = await ctx.store.fetchall(
        "SELECT title, due_date FROM tasks_items "
        "WHERE status = 'pending' AND due_date < ? ORDER BY due_date LIMIT 8",
        (today,),
    )
    upcoming = await ctx.store.fetchall(
        "SELECT title, due_date FROM tasks_items "
        "WHERE status = 'pending' AND due_date >= ? AND due_date <= ? "
        "ORDER BY due_date LIMIT 8",
        (today, week),
    )
    lines = []
    if overdue:
        lines.append("⏰ Overdue:\n" + "\n".join(
            f"  {t['title']} (was {t['due_date']})" for t in overdue))
    if upcoming:
        lines.append("✅ This week:\n" + "\n".join(
            f"  {t['title']} ({t['due_date']})" for t in upcoming))
    if not lines:
        lines.append("✅ No dated tasks pending. Suspiciously tidy.")
    return "\n\n".join(lines)


async def _home_section(ctx: AppContext) -> str:
    cutoff = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    due = await ctx.store.fetchall(
        "SELECT name, next_due FROM home_tasks "
        "WHERE next_due IS NOT NULL AND next_due <= ? ORDER BY next_due LIMIT 5",
        (cutoff,),
    )
    if not due:
        return ""
    lines = [f"  {t['name'].replace('_', ' ').title()} ({t['next_due']})" for t in due]
    return "🏠 House upkeep due:\n" + "\n".join(lines)


async def build_review(ctx: AppContext) -> str:
    sections = [
        await _calendar_section(ctx),
        await _money_section(ctx),
        await _tasks_section(ctx),
        await _home_section(ctx),
    ]
    body = "\n\n".join(s for s in sections if s)

    closing = ""
    try:
        closing = await ctx.brain.complete(
            f"Here is the owner's weekly review:\n\n{body}\n\n"
            "In 2-3 sentences, as their wise assistant: what single thing "
            "matters most this week, and one thing they might be missing. "
            "No repetition of the lists above.",
            tier=Tier.REASON, max_tokens=200,
        )
    except Exception:
        logger.exception("review closing failed — sending review without it")

    header = "🗓 **Sunday Sit-Down**\n\n"
    return header + body + (f"\n\n🦉 {closing}" if closing else "")


async def handle_weekreview(ctx: AppContext, update, context) -> str:
    return await build_review(ctx)


async def job_sunday_review(ctx) -> None:
    await ctx.bot.send_message(await build_review(ctx))
