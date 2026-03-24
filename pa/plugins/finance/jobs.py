"""Finance scheduled jobs — autonomous financial monitoring with self-healing."""
import asyncio
from pa.plugins import Job


async def _retry(coro_fn, ctx, max_retries=3, source="finance"):
    """Self-healing retry wrapper. Logs errors, retries with backoff."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except Exception as e:
            last_error = e
            await ctx.brain.log_error(source, e)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    # Final failure — notify user
    try:
        await ctx.bot.send_message(f"Job {source} failed after {max_retries} retries: {last_error}")
    except Exception:
        pass
    return None


async def detect_recurring_payments(ctx) -> None:
    """Analyze transactions to auto-detect recurring payments, subscriptions, and income."""
    from pa.plugins.finance.repository import FinanceRepository
    from pa.core.tier import Tier
    import datetime, json, re

    repo = FinanceRepository(ctx.store)
    since = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=500)
    debits = [t for t in txns if t['amount'] > 0]

    if not debits:
        return

    txn_list = "\n".join(
        f"{t['date']} {t['description'][:50]} ${t['amount']:,.2f}"
        for t in debits[:100]
    )

    SYSTEM = """Analyze these bank transactions and identify:
1. Recurring monthly payments (mortgage, rent, utilities, subscriptions, insurance)
2. Subscriptions (streaming, apps, memberships — even small ones like $5.99)
3. Regular income deposits (look at credits/deposits)
Return ONLY JSON:
{
  "recurring_payments": [{"description": "...", "amount": 0.00, "frequency": "monthly", "category": "mortgage|utility|subscription|insurance|other", "likely_institution": "...", "cancellable": true|false}],
  "subscriptions": [{"description": "...", "amount": 0.00, "frequency": "monthly", "service": "..."}],
  "income_sources": [{"description": "...", "amount": 0.00, "frequency": "biweekly|monthly|irregular"}],
  "spending_concerns": ["list of specific spending patterns that seem high or wasteful"]
}"""

    try:
        text = await ctx.brain.query(
            txn_list, system_prompt=SYSTEM,
            tier=Tier.FAST, use_conversation=False,
        )
        text = text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        start = text.find('{')
        end = text.rfind('}')
        if start == -1:
            return
        text = re.sub(r',\s*([}\]])', r'\1', text[start:end+1])
        data = json.loads(text)

        from pa.plugins.finance.advisor import save_profile
        recurring = data.get('recurring_payments', [])
        subscriptions = data.get('subscriptions', [])
        income = data.get('income_sources', [])
        concerns = data.get('spending_concerns', [])

        # Find mortgage
        mortgage = next((p for p in recurring if p.get('category') == 'mortgage'), None)
        if mortgage:
            await save_profile(ctx, 'mortgage_payment', mortgage['amount'])
            await save_profile(ctx, 'mortgage_description', mortgage['description'])

        # Monthly income estimate
        if income:
            monthly_income = sum(
                i['amount'] * (2 if i.get('frequency') == 'biweekly' else 1)
                for i in income
            )
            if monthly_income > 0:
                await save_profile(ctx, 'monthly_income', monthly_income)

        await save_profile(ctx, 'recurring_payments', recurring)
        await save_profile(ctx, 'subscriptions', subscriptions)
        await save_profile(ctx, 'income_sources', income)
        await save_profile(ctx, 'spending_concerns', concerns)
        await save_profile(ctx, 'recurring_updated', datetime.date.today().isoformat())

    except Exception as e:
        await ctx.brain.log_error("detect_recurring", e)


async def job_morning_sync(ctx) -> None:
    """Every morning — sync accounts, build comprehensive morning briefing."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_sync():
        import datetime
        from collections import defaultdict
        from pa.plugins.teller.sync import sync_teller_accounts
        from pa.plugins.finance.repository import FinanceRepository
        from pa.plugins.finance.merchants import categorize_transactions
        from pa.core.tier import Tier

        # 1. Sync latest data from Teller
        await sync_teller_accounts(ctx)

        # On Mondays, also detect recurring payments
        if datetime.date.today().weekday() == 0:
            await detect_recurring_payments(ctx)

        repo = FinanceRepository(ctx.store)
        parts = []

        # 2. Balances — checking & savings
        balances = await repo.get_latest_balances()
        checking = [b for b in balances if b['type'] in ('checking', 'depository')]
        savings = [b for b in balances if b['type'] == 'savings']
        credit = [b for b in balances if b['type'] in ('credit', 'credit_card')]

        bal_bits = []
        for b in checking:
            bal_bits.append(f"Checking ${b['balance']:,.2f}")
        for b in savings:
            bal_bits.append(f"Savings ${b['balance']:,.2f}")
        if bal_bits:
            parts.append("\U0001f4b0 " + ", ".join(bal_bits))

        # 3. Yesterday's spending with merchant categories
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        txns = await repo.get_transactions(since_date=yesterday, limit=200)
        yesterday_debits = [t for t in txns if t['date'] == yesterday and t['amount'] > 0]

        if yesterday_debits:
            await categorize_transactions(ctx.store, yesterday_debits)
            total_spent = sum(t['amount'] for t in yesterday_debits)
            # Group by category
            by_cat = defaultdict(float)
            for t in yesterday_debits:
                cat = t.get('learned_category') or 'Other'
                # Use top-level category only (e.g. "Food" from "Food/Dining")
                cat_short = cat.split('/')[0]
                by_cat[cat_short] += t['amount']
            # Sort by amount descending
            cat_parts = [f"{cat} ${amt:,.0f}" for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1])]
            parts.append(f"\U0001f4ca Yesterday: ${total_spent:,.2f} spent ({', '.join(cat_parts)})")
        else:
            parts.append("\U0001f4ca Yesterday: No spending recorded.")

        # 4. Bills due in next 7 days
        today = datetime.date.today()
        due_soon = []
        for b in balances:
            if b.get('due_date'):
                try:
                    due = datetime.date.fromisoformat(b['due_date'])
                    days_until = (due - today).days
                    if 0 <= days_until <= 7:
                        amt = b.get('minimum_payment') or b.get('statement_balance') or b['balance']
                        due_soon.append((days_until, b['institution'], b['name'], amt))
                except Exception:
                    pass
        if due_soon:
            due_soon.sort()
            due_lines = []
            for days_until, inst, name, amt in due_soon:
                day_str = "today" if days_until == 0 else f"in {days_until}d"
                due_lines.append(f"{inst} {name} ${amt:,.2f} ({day_str})")
            parts.append("\U0001f4c5 Due this week: " + " | ".join(due_lines))

        # 5. Alerts — low balance, unusual spending, credit card balances
        alerts = []
        for b in checking:
            if b['balance'] < 500:
                alerts.append(f"Low checking balance: ${b['balance']:,.2f}")
        for b in credit:
            if b['balance'] > 0:
                limit = b.get('credit_limit')
                if limit and b['balance'] / limit > 0.5:
                    alerts.append(f"{b['name']} at {b['balance']/limit:.0%} utilization (${b['balance']:,.2f})")
        # Flag high spending day
        if yesterday_debits:
            total_spent = sum(t['amount'] for t in yesterday_debits)
            if total_spent > 300:
                alerts.append(f"Heavy spending day yesterday (${total_spent:,.2f})")
        if alerts:
            parts.append("\u26a0\ufe0f " + " | ".join(alerts))

        if not parts:
            return  # Nothing to report

        message = "Good morning Steven.\n\n" + "\n".join(parts)
        await ctx.bot.send_message(message)

    await _retry(_do_sync, ctx, source="morning_sync")


async def job_weekly_advisor(ctx) -> None:
    """Sunday morning — full pull: Teller sync + Gmail bill scan + advisor analysis."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_weekly():
        from pa.plugins.teller.sync import sync_teller_accounts
        from pa.plugins.finance.advisor import run_advisor

        await sync_teller_accounts(ctx)
        await detect_recurring_payments(ctx)
        result = await run_advisor(ctx, include_gmail=True)
        await ctx.bot.send_message(f"Weekly Financial Report\n\n{result}")

    await _retry(_do_weekly, ctx, source="weekly_advisor")


async def job_balance_check(ctx) -> None:
    """Every 4 hours — sync balance, alert if low."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_check():
        from pa.plugins.teller.sync import sync_teller_accounts
        from pa.plugins.finance.repository import FinanceRepository
        await sync_teller_accounts(ctx, institutions=['wellsfargo'])
        repo = FinanceRepository(ctx.store)
        balances = await repo.get_latest_balances()
        checking = [b for b in balances if b['type'] in ('checking', 'savings', 'depository')]
        for acct in checking:
            if acct['balance'] < 200:
                await ctx.bot.send_message(
                    f"Low balance: {acct['institution']} {acct['name']} "
                    f"at ${acct['balance']:,.2f}"
                )

    await _retry(_do_check, ctx, source="balance_check")


async def job_due_date_check(ctx) -> None:
    """Daily — check for bills due in next 3 days."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_due():
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
                            f"{b['institution']} {b['name']}: "
                            f"${b.get('minimum_payment', b['balance']):,.2f} due in {days_until} day(s)"
                        )
                except Exception:
                    pass
        if urgent:
            await ctx.bot.send_message(
                "Bills due soon:\n" + "\n".join(urgent)
            )

    await _retry(_do_due, ctx, source="due_date_check")


def get_finance_jobs() -> list[Job]:
    return [
        Job(name="morning_sync", handler=job_morning_sync,
            trigger="cron", kwargs={"hour": 7, "minute": 0}),
        Job(name="balance_check", handler=job_balance_check,
            trigger="interval", kwargs={"hours": 4}),
        Job(name="due_date_check", handler=job_due_date_check,
            trigger="cron", kwargs={"hour": 8, "minute": 0}),
        Job(name="weekly_advisor", handler=job_weekly_advisor,
            trigger="cron", kwargs={"day_of_week": "sun", "hour": 8, "minute": 0}),
    ]
