import time
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
    if not institution:
        return "Usage: /scrape <institution>\nExample: /scrape wellsfargo"

    creds = ctx.vault.get(institution)
    if not creds:
        return f"No credentials for '{institution}'. Use /addcred {institution} first."

    scrapers = _get_scrapers()
    if institution not in scrapers:
        available = ", ".join(scrapers.keys()) or "none"
        return f"No scraper for '{institution}'. Available: {available}"

    repo = _repo(ctx)
    start_time = time.time()

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--js-flags=--max-old-space-size=256",
                ],
            )
            browser_ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                java_script_enabled=True,
            )
            # Block heavy resources to speed up page loads on Pi
            await browser_ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,eot}", lambda route: route.abort())
            await browser_ctx.route("**/{analytics,tracking,ads,beacon,pixel}**", lambda route: route.abort())

            from pa.scrapers.mfa_bridge import MFABridge
            mfa_bridge = ctx.bot._mfa_bridge
            scraper_cls = scrapers[institution]
            scraper = scraper_cls(browser_ctx, mfa_bridge)
            await scraper.open()

            try:
                await update.message.reply_text(f"Scraping {institution}...")
                await scraper.login(creds)

                balances = await scraper.get_balances()
                if not balances:
                    await repo.log_scrape(institution, "failure",
                                          error_message="No balances found")
                    return f"Logged in to {institution} but found no account data."

                accounts = await repo.get_accounts()
                inst_accounts = {a["name"]: a["id"] for a in accounts
                                 if a["institution"] == institution}

                saved = 0
                for bal in balances:
                    account_name = getattr(bal, "account_name", institution)
                    account_type = getattr(bal, "account_type", "checking")

                    if account_name not in inst_accounts:
                        aid = await repo.add_account(
                            institution, account_name, account_type,
                            interest_rate=getattr(bal, "interest_rate", None),
                            credit_limit=bal.available_credit,
                        )
                        inst_accounts[account_name] = aid
                    else:
                        aid = inst_accounts[account_name]

                    await repo.add_balance(
                        aid, bal.balance,
                        statement_balance=bal.statement_balance,
                        available_credit=bal.available_credit,
                        minimum_payment=bal.minimum_payment,
                        due_date=bal.due_date,
                    )
                    saved += 1

                duration = time.time() - start_time
                await repo.log_scrape(institution, "success",
                                      duration_seconds=duration)
                await scraper.logout()
                return f"Done! Scraped {saved} account(s) from {institution} in {duration:.1f}s."

            finally:
                await scraper.close()
                await browser.close()

    except Exception as e:
        duration = time.time() - start_time
        await repo.log_scrape(institution, "failure",
                              error_message=str(e), duration_seconds=duration)
        return f"Scrape failed: {e}"


def _get_scrapers() -> dict[str, type]:
    from pa.plugins.finance.scrapers.wellsfargo import WellsFargoScraper
    return {
        "wellsfargo": WellsFargoScraper,
    }


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
