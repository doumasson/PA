"""Research command and NL handlers."""
from __future__ import annotations

import logging
from pa.core.tier import Tier
from pa.plugins import AppContext

log = logging.getLogger(__name__)

RESEARCH_SYSTEM = """You are a research assistant. The user wants to know about a topic.
Provide a clear, well-organized summary covering:
1. What it is / current state
2. Key facts and figures
3. Recent developments
4. Why it matters

Be specific and factual. If you don't know something recent, say so.
Keep it concise but thorough — aim for 200-400 words."""


async def do_research(ctx: AppContext, topic: str) -> str:
    """Run a research query on a topic using Sonnet and save results."""
    result = await ctx.brain.query(
        f"Research this topic thoroughly: {topic}",
        system_prompt=RESEARCH_SYSTEM,
        tier=Tier.STANDARD,
        use_conversation=False,
    )

    await ctx.store.execute(
        "INSERT INTO research_queries (query, summary) VALUES (?, ?)",
        (topic, result[:2000]),
    )

    return result


async def handle_research(update, context, ctx: AppContext) -> None:
    """Handle /research <topic> command."""
    text = update.message.text or ""
    topic = text.split(maxsplit=1)[1].strip() if " " in text else ""
    if not topic:
        await update.message.reply_text("Usage: /research <topic>")
        return

    await update.message.reply_text(f"Researching *{topic}*...", parse_mode="Markdown")
    try:
        result = await do_research(ctx, topic)
        # Telegram has a 4096 char limit per message
        if len(result) > 4000:
            for i in range(0, len(result), 4000):
                await update.message.reply_text(result[i:i + 4000])
        else:
            await update.message.reply_text(result)
    except Exception as e:
        log.error("Research failed: %s", e, exc_info=True)
        await update.message.reply_text(f"Research failed: {e}")


async def handle_watch(update, context, ctx: AppContext) -> None:
    """Handle /watch <topic> — add topic to watchlist."""
    text = update.message.text or ""
    topic = text.split(maxsplit=1)[1].strip() if " " in text else ""
    if not topic:
        await update.message.reply_text("Usage: /watch <topic>")
        return

    existing = await ctx.store.fetchone(
        "SELECT id FROM research_watchlist WHERE topic = ?", (topic,)
    )
    if existing:
        await update.message.reply_text(f"Already watching: *{topic}*", parse_mode="Markdown")
        return

    await ctx.store.execute(
        "INSERT INTO research_watchlist (topic) VALUES (?)", (topic,)
    )
    await update.message.reply_text(
        f"Now watching: *{topic}*\nI'll check for updates on Wednesdays and Saturdays.",
        parse_mode="Markdown",
    )


async def handle_watchlist(update, context, ctx: AppContext) -> None:
    """Handle /watchlist — show all watched topics."""
    rows = await ctx.store.fetchall(
        "SELECT topic, last_checked, last_summary FROM research_watchlist ORDER BY created_at"
    )
    if not rows:
        await update.message.reply_text("No topics on your watchlist. Use /watch <topic> to add one.")
        return

    lines = ["**Research Watchlist:**\n"]
    for r in rows:
        checked = r["last_checked"] or "never"
        summary_preview = ""
        if r["last_summary"]:
            summary_preview = f"\n  _{r['last_summary'][:80]}..._"
        lines.append(f"- **{r['topic']}** (last checked: {checked}){summary_preview}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_research_nl(update, context, ctx: AppContext) -> None:
    """Handle natural language research queries."""
    text = (update.message.text or "").strip()

    # Strip common prefixes to extract the actual topic
    lower = text.lower()
    prefixes = [
        "what's happening with", "what is happening with",
        "tell me about", "research", "look into",
        "what do you know about", "news about",
        "latest on", "update on", "find out about",
    ]
    topic = text
    for prefix in prefixes:
        if lower.startswith(prefix):
            topic = text[len(prefix):].strip()
            break

    if not topic:
        await update.message.reply_text("What would you like me to research?")
        return

    await update.message.reply_text(f"Looking into *{topic}*...", parse_mode="Markdown")
    try:
        result = await do_research(ctx, topic)
        if len(result) > 4000:
            for i in range(0, len(result), 4000):
                await update.message.reply_text(result[i:i + 4000])
        else:
            await update.message.reply_text(result)
    except Exception as e:
        log.error("Research NL failed: %s", e, exc_info=True)
        await update.message.reply_text(f"Research failed: {e}")
