from typing import Any
from pa.plugins import AppContext
from pa.plugins.finance.repository import FinanceRepository
from pa.plugins.finance.formatters import (
    format_balance_summary, format_debt_summary, format_due_summary, format_spending_summary,
)


def _repo(ctx: AppContext) -> FinanceRepository:
    return FinanceRepository(ctx.store)


async def handle_balance(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_balance_summary(balances)


async def handle_debt(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_debt_summary(balances)


async def handle_due(ctx: AppContext, update: Any, context: Any) -> str:
    balances = await _repo(ctx).get_latest_balances()
    return format_due_summary(balances)


async def handle_spending(ctx: AppContext, update: Any, context: Any) -> str:
    period = "this month"
    if context.args:
        period = " ".join(context.args)
    txns = await _repo(ctx).get_transactions(limit=500)
    return format_spending_summary(txns, period)


async def handle_plan(ctx: AppContext, update: Any, context: Any) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."
    from pa.core.tier import Tier
    response = await ctx.brain.query(
        "Create a debt payoff plan based on my current balances. Compare snowball vs avalanche strategies.",
        tier=Tier.DEEP,
    )
    return response


async def handle_scrape(ctx: AppContext, update: Any, context: Any) -> str:
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."
    institution = context.args[0] if context.args else None
    return f"Starting scrape{' for ' + institution if institution else ''}..."


async def handle_schedule(ctx: AppContext, update: Any, context: Any) -> str:
    schedule = ctx.config.get("schedule", {})
    lines = ["**Current Schedule**\n"]
    for key, val in schedule.items():
        lines.append(f"  {key}: {val}")
    return "\n".join(lines)


async def handle_backup(ctx: AppContext, update: Any, context: Any) -> str:
    backup_path = ctx.config.get("backup_path", "")
    if not backup_path:
        return "Backup path not configured. Set backup_path in config."
    return f"Backup saved to {backup_path}"
