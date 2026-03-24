"""Teller scheduled jobs."""
from pa.plugins import Job


async def morning_sync(ctx) -> None:
    """Every morning: sync WF, send spending summary."""
    if not ctx.vault.is_unlocked:
        return
    from pa.plugins.teller.sync import sync_teller_accounts, get_yesterday_summary
    await sync_teller_accounts(ctx, institutions=['wellsfargo'])
    summary = await get_yesterday_summary(ctx)
    if summary:
        await ctx.bot.send_message(summary)


async def weekly_sync(ctx) -> None:
    """Weekly: sync all accounts."""
    if not ctx.vault.is_unlocked:
        return
    from pa.plugins.teller.sync import sync_teller_accounts
    results = await sync_teller_accounts(ctx)
    await ctx.bot.send_message("Weekly sync complete:\n" + "\n".join(results))


def get_teller_jobs() -> list[Job]:
    return []  # Handled by finance jobs
