"""Financial advisor commands."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from pa.plugins import AppContext


async def handle_advisor(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked."
    question = " ".join(context.args) if context.args else None
    await update.message.reply_text("Consulting the ledgers...")
    from pa.plugins.finance.advisor import run_advisor
    return await run_advisor(ctx, user_question=question)


async def handle_debt_update(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked."
    args = context.args or []
    if len(args) < 3:
        return "Usage: /debt_add <institution> <account_name> <balance> [status]\nExample: /debt_add synchrony homedepot 1500 charged_off"
    institution = args[0]
    account_name = args[1]
    balance = float(args[2])
    status = args[3] if len(args) > 3 else 'current'
    from pa.plugins.finance.advisor import update_debt
    await update_debt(ctx, institution, account_name, balance, status=status)
    return f"Updated: {institution} {account_name} ${balance:,.2f} [{status}]"


async def handle_advisor_nl(ctx: AppContext, text: str, update: Update) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked."
    await update.message.reply_text("Consulting the ledgers...")
    from pa.plugins.finance.advisor import run_advisor
    return await run_advisor(ctx, user_question=text)
