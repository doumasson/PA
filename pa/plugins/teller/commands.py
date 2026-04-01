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

    # Merchant search - "how much at X", "spent at X", "spending at X"
    import re
    from pa.plugins.finance.merchants import get_category
    merchant_match = re.search(
        r"(?:how much\s+(?:have\s+i\s+)?(?:spent?|spend)\s+(?:at|on)\s+|spent?\s+at\s+|spend(?:ing)?\s+at\s+|how (?:much|often)\s+(?:at|do i (?:spend|go to))\s+)([a-zA-Z0-9 &\']+?)(?:\s+(?:in|over|last|this|the|today|lately).*)?$",
        tl
    )
    if merchant_match:
        merchant = merchant_match.group(1).strip()
        if len(merchant) > 2:
            category = await get_category(ctx.store, merchant)
            label = f"{merchant} ({category})" if category else merchant
            await update.message.reply_text(f"Searching transactions for {label}...")
            return await get_spending_by_merchant(ctx, merchant)

    return None
