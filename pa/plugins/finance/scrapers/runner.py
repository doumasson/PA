"""Runs the scraper agent for one or all institutions."""
from __future__ import annotations
from pa.plugins.finance.scrapers.agent import ScraperAgent
from pa.plugins.finance.repository import FinanceRepository
import datetime


async def run_scrape(institution: str, ctx, notify_callback=None) -> str:
    """Scrape one institution and save results to db."""
    agent = ScraperAgent(
        store=ctx.store,
        vault=ctx.vault,
        brain=ctx.brain,
        mfa_bridge=getattr(ctx, 'mfa_bridge', None),
    )

    result = await agent.scrape(institution, notify_callback=notify_callback)

    if result.get('error'):
        return f"Failed to scrape {institution}: {result['error']}"

    balances = result.get('balances', [])
    if not balances:
        return f"Logged into {institution} but found no balance data."

    repo = FinanceRepository(ctx.store)
    saved = 0
    for b in balances:
        # Get or create account
        accounts = await repo.get_accounts()
        account = next((a for a in accounts
                       if a['institution'].lower() == institution.lower()
                       and a['name'].lower() == b.get('name', '').lower()), None)

        if not account:
            account_id = await repo.add_account(
                institution=institution,
                name=b.get('name', institution),
                account_type=b.get('type', 'unknown'),
            )
        else:
            account_id = account['id']

        await repo.add_balance(
            account_id=account_id,
            balance=b.get('balance', 0),
            minimum_payment=b.get('minimum_payment'),
            due_date=b.get('due_date'),
        )
        saved += 1

    return f"Scraped {institution}: found {saved} account(s). Use /balance to see results."


async def run_all_scrapes(ctx, notify_callback=None) -> str:
    """Scrape all institutions that have credentials in the vault."""
    skip = {'google_token', 'google_credentials', '_salt'}
    institutions = [k for k in ctx.vault._data.keys() if k not in skip]

    if not institutions:
        return "No credentials stored. Use /addcred to add your financial institutions."

    results = []
    for inst in institutions:
        if notify_callback:
            await notify_callback(f"Scraping {inst}...")
        result = await run_scrape(inst, ctx, notify_callback)
        results.append(result)

    return "\n".join(results)
