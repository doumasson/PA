"""Teller plugin commands."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from pa.plugins import AppContext


async def handle_sync(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked."
    await update.message.reply_text("Syncing accounts...")
    from pa.plugins.teller.sync import sync_teller_accounts
    results = await sync_teller_accounts(ctx)
    return "\n".join(results)


async def handle_teller_nl(ctx: AppContext, text: str, update: Update) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked."
    from pa.plugins.teller.sync import (
        sync_teller_accounts, get_yesterday_summary,
        get_weekly_spending_summary, get_spending_by_merchant
    )
    tl = text.lower()

    if any(w in tl for w in ["sync", "update accounts", "refresh", "pull latest"]):
        await update.message.reply_text("Syncing now...")
        results = await sync_teller_accounts(ctx)
        return "\n".join(results)

    if any(w in tl for w in ["yesterday", "morning update"]):
        summary = await get_yesterday_summary(ctx)
        return summary or "No data yet. Try /sync first."

    if any(w in tl for w in ["week", "7 days", "last week", "weekly"]):
        await update.message.reply_text("Reviewing your week...")
        return await get_weekly_spending_summary(ctx)

    # Merchant search - "how much at X" or "spent at X"
    import re
    merchant_match = re.search(
        r"(?:how much|spent?|spend|at|on)\s+(?:at\s+|on\s+)?([a-zA-Z0-9 &\']+?)(?:\s+(?:in|over|last|this|the).*)?$",
        tl
    )
    if merchant_match and any(w in tl for w in ["how much", "spent at", "spend at", "at ", "how often"]):
        merchant = merchant_match.group(1).strip()
        if len(merchant) > 2:
            await update.message.reply_text(f"Searching transactions for {merchant}...")
            return await get_spending_by_merchant(ctx, merchant)

    return None
