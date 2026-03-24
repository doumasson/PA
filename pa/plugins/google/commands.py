"""Gmail plugin commands."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_gmail_check(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Manually trigger a Gmail check."""
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    await update.message.reply_text("Checking Gmail...")

    from pa.plugins.google.jobs import check_gmail
    await check_gmail(ctx)
    return "Done. I'll message you if anything needs attention."


async def handle_gmail_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Handle natural language Gmail/calendar queries."""
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    tl = text.lower()

    if any(w in tl for w in ["check", "any emails", "what's in", "inbox", "new email", "unread"]):
        await update.message.reply_text("Checking Gmail now...")
        from pa.plugins.google.jobs import check_gmail
        from pa.plugins.google.client import gmail_service
        from pa.plugins.google.gmail import get_unread_since
        try:
            gmail = gmail_service(ctx.vault)
            emails = get_unread_since(gmail, max_results=5)
            count = len(emails)
            if count == 0:
                return "No unread emails."
            return f"You have {count} unread emails. Triaging now..."
        except Exception as e:
            return f"Gmail error: {e}"

    return await ctx.brain.query(
        f"User asked about email/calendar: '{text}'. "
        f"Tell them they can use /gmail to check email, or ask me to check for them.",
        tier=Tier.FAST
    )
