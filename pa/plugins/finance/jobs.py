"""Finance scheduled jobs - autonomous financial monitoring."""
from pa.plugins import Job


async def detect_recurring_payments(ctx) -> None:
    """Analyze WF transactions to auto-detect recurring payments like mortgage."""
    from pa.plugins.finance.repository import FinanceRepository
    from pa.core.tier import Tier
    import datetime, json

    repo = FinanceRepository(ctx.store)
    since = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=500)
    debits = [t for t in txns if t['amount'] > 100]  # Only significant payments

    if not debits:
        return

    # Ask Claude to identify recurring payments
    txn_list = "\n".join(
        f"{t['date']} {t['description'][:50]} ${t['amount']:,.2f}"
        for t in debits[:100]
    )

    SYSTEM = """Analyze these bank transactions and identify:
1. Recurring monthly payments (mortgage, rent, utilities, subscriptions)
2. Regular income deposits
Return ONLY JSON:
{
  "recurring_payments": [{"description": "...", "amount": 0.00, "frequency": "monthly", "category": "mortgage|utility|subscription|insurance|other", "likely_institution": "..."}],
  "income_sources": [{"description": "...", "amount": 0.00, "frequency": "biweekly|monthly|irregular"}]
}"""

    try:
        text = await ctx.brain.query(txn_list, system_prompt=SYSTEM, tier=Tier.FAST)
        text = text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        start = text.find('{')
        end = text.rfind('}')
        if start == -1:
            return
        data = json.loads(text[start:end+1])

        # Save findings to profile
        from pa.plugins.finance.advisor import save_profile
        recurring = data.get('recurring_payments', [])
        income = data.get('income_sources', [])

        # Find mortgage specifically
        mortgage = next((p for p in recurring if p.get('category') == 'mortgage'), None)
        if mortgage:
            await save_profile(ctx, 'mortgage_payment', mortgage['amount'])
            await save_profile(ctx, 'mortgage_description', mortgage['description'])
            print(f"Detected mortgage: {mortgage['description']} ${mortgage['amount']:,.2f}")

        # Save total estimated income
        if income:
            monthly_income = sum(
                i['amount'] * (2 if i.get('frequency') == 'biweekly' else 1)
                for i in income
            )
            if monthly_income > 0:
                await save_profile(ctx, 'monthly_income', monthly_income)

        await save_profile(ctx, 'recurring_payments', recurring)
        await save_profile(ctx, 'income_sources', income)

    except Exception as e:
        print(f"Recurring payment detection error: {e}")


async def detect_recurring_payments(ctx) -> None:
    """Analyze WF transactions to auto-detect recurring payments like mortgage."""
    from pa.plugins.finance.repository import FinanceRepository
    from pa.core.tier import Tier
    import datetime, json

    repo = FinanceRepository(ctx.store)
    since = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=500)
    debits = [t for t in txns if t['amount'] > 100]  # Only significant payments

    if not debits:
        return

    # Ask Claude to identify recurring payments
    txn_list = "\n".join(
        f"{t['date']} {t['description'][:50]} ${t['amount']:,.2f}"
        for t in debits[:100]
    )

    SYSTEM = """Analyze these bank transactions and identify:
1. Recurring monthly payments (mortgage, rent, utilities, subscriptions)
2. Regular income deposits
Return ONLY JSON:
{
  "recurring_payments": [{"description": "...", "amount": 0.00, "frequency": "monthly", "category": "mortgage|utility|subscription|insurance|other", "likely_institution": "..."}],
  "income_sources": [{"description": "...", "amount": 0.00, "frequency": "biweekly|monthly|irregular"}]
}"""

    try:
        text = await ctx.brain.query(txn_list, system_prompt=SYSTEM, tier=Tier.FAST)
        text = text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        start = text.find('{')
        end = text.rfind('}')
        if start == -1:
            return
        data = json.loads(text[start:end+1])

        # Save findings to profile
        from pa.plugins.finance.advisor import save_profile
        recurring = data.get('recurring_payments', [])
        income = data.get('income_sources', [])

        # Find mortgage specifically
        mortgage = next((p for p in recurring if p.get('category') == 'mortgage'), None)
        if mortgage:
            await save_profile(ctx, 'mortgage_payment', mortgage['amount'])
            await save_profile(ctx, 'mortgage_description', mortgage['description'])
            print(f"Detected mortgage: {mortgage['description']} ${mortgage['amount']:,.2f}")

        # Save total estimated income
        if income:
            monthly_income = sum(
                i['amount'] * (2 if i.get('frequency') == 'biweekly' else 1)
                for i in income
            )
            if monthly_income > 0:
                await save_profile(ctx, 'monthly_income', monthly_income)

        await save_profile(ctx, 'recurring_payments', recurring)
        await save_profile(ctx, 'income_sources', income)

    except Exception as e:
        print(f"Recurring payment detection error: {e}")


async def job_morning_sync(ctx) -> None:
    """Every morning - sync WF, send summary if anything notable."""
    if not ctx.vault.is_unlocked:
        return
    try:
        from pa.plugins.teller.sync import sync_teller_accounts, get_yesterday_summary
        await sync_teller_accounts(ctx)
        # Auto-detect recurring payments weekly (Monday only)
        import datetime
        if datetime.date.today().weekday() == 0:
            await detect_recurring_payments(ctx)
        summary = await get_yesterday_summary(ctx)
        if summary:
            await ctx.bot.send_message(summary)
    except Exception as e:
        print(f"Morning sync error: {e}")


async def job_weekly_advisor(ctx) -> None:
    """Sunday morning - full advisor run with Gmail bill scan."""
    if not ctx.vault.is_unlocked:
        return
    try:
        from pa.plugins.teller.sync import sync_teller_accounts
        from pa.plugins.finance.advisor import run_advisor
        # Sync all Teller accounts first
        await sync_teller_accounts(ctx)
        # Run full advisor (includes Gmail bill scan)
        result = await run_advisor(ctx)
        await ctx.bot.send_message(result)
    except Exception as e:
        await ctx.bot.send_message(f"Weekly advisor error: {e}")


async def job_balance_check(ctx) -> None:
    """Every 4 hours - sync WF balance, alert if low."""
    if not ctx.vault.is_unlocked:
        return
    try:
        from pa.plugins.teller.sync import sync_teller_accounts
        from pa.plugins.finance.repository import FinanceRepository
        await sync_teller_accounts(ctx, institutions=['wellsfargo'])
        repo = FinanceRepository(ctx.store)
        balances = await repo.get_latest_balances()
        checking = [b for b in balances if b['type'] in ('checking', 'savings', 'depository')]
        for acct in checking:
            if acct['balance'] < 200:
                await ctx.bot.send_message(
                    f"⚠️ Low balance alert: {acct['institution']} {acct['name']} "
                    f"is down to ${acct['balance']:,.2f}"
                )
    except Exception as e:
        print(f"Balance check error: {e}")


async def job_due_date_check(ctx) -> None:
    """Daily - check for bills due in next 3 days."""
    if not ctx.vault.is_unlocked:
        return
    try:
        import datetime
        from pa.plugins.finance.repository import FinanceRepository
        repo = FinanceRepository(ctx.store)
        balances = await repo.get_latest_balances()
        today = datetime.date.today()
        urgent = []
        for b in balances:
            if b.get('due_date'):
                try:
                    due = datetime.date.fromisoformat(b['due_date'])
                    days_until = (due - today).days
                    if 0 <= days_until <= 3:
                        urgent.append(
                            f"📅 {b['institution']} {b['name']}: "
                            f"${b.get('minimum_payment', b['balance']):,.2f} due in {days_until} days"
                        )
                except Exception:
                    pass
        if urgent:
            await ctx.bot.send_message(
                "⚠️ Bills due soon:\n" + "\n".join(urgent)
            )
    except Exception as e:
        print(f"Due date check error: {e}")


def get_finance_jobs() -> list[Job]:
    return [
        # Every morning at 7am - sync + spending summary
        Job(name="morning_sync", handler=job_morning_sync,
            trigger="cron", kwargs={"hour": 7, "minute": 0}),
        # Every 4 hours - balance check, alert if low
        Job(name="balance_check", handler=job_balance_check,
            trigger="interval", kwargs={"hours": 4}),
        # Daily at 8am - due date alerts
        Job(name="due_date_check", handler=job_due_date_check,
            trigger="cron", kwargs={"hour": 8, "minute": 0}),
        # Sunday 8am - full advisor run
        Job(name="weekly_advisor", handler=job_weekly_advisor,
            trigger="cron", kwargs={"day_of_week": "sun", "hour": 8, "minute": 0}),
    ]
