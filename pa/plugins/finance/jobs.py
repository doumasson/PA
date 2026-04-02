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

        # Calculate and save total monthly subscription cost
        sub_total = sum(s.get('amount', 0) for s in subscriptions)
        # Also include recurring payments categorized as subscriptions
        sub_total += sum(
            p.get('amount', 0) for p in recurring
            if p.get('category') == 'subscription'
        )
        if sub_total > 0:
            await save_profile(ctx, 'subscription_total', round(sub_total, 2))

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

        # 6. Subscription total if significant
        from pa.plugins.finance.advisor import load_profile
        profile = await load_profile(ctx)
        sub_total = profile.get('subscription_total', 0)
        if sub_total and sub_total > 50:
            parts.append(f"\U0001f4e6 You're paying ${sub_total:,.2f}/month in subscriptions.")

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


async def job_bill_reminders(ctx) -> None:
    """Daily at 8:30am — remind about upcoming bills, reset paid_this_cycle on 1st of month."""
    async def _do_bill_reminders():
        import datetime

        today = datetime.date.today()

        # Reset paid_this_cycle on the 1st of each month
        if today.day == 1:
            await ctx.store.execute(
                "UPDATE finance_bills SET paid_this_cycle = 0, updated_at = CURRENT_TIMESTAMP"
            )

        # Check for unpaid bills due in next 3 days
        cutoff = (today + datetime.timedelta(days=3)).isoformat()
        today_str = today.isoformat()
        bills = await ctx.store.fetchall(
            "SELECT name, amount, due_date FROM finance_bills "
            "WHERE paid_this_cycle = 0 AND due_date IS NOT NULL "
            "AND due_date >= ? AND due_date <= ? "
            "ORDER BY due_date",
            (today_str, cutoff),
        )
        if bills:
            lines = []
            for b in bills:
                amt_str = f"${b['amount']:,.2f}" if b.get('amount') else "amount TBD"
                lines.append(f"  {b['name']}: {amt_str} due {b['due_date']}")
            await ctx.bot.send_message(
                "Bills due soon:\n" + "\n".join(lines)
            )

    await _retry(_do_bill_reminders, ctx, source="bill_reminders")


async def job_spending_pace_check(ctx) -> None:
    """Daily at noon — alert if spending pace exceeds 120% of average."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_pace():
        import datetime
        from pa.plugins.finance.repository import FinanceRepository

        repo = FinanceRepository(ctx.store)
        today = datetime.date.today()
        first_of_month = today.replace(day=1)
        days_elapsed = (today - first_of_month).days or 1

        # Need at least 5 days of data for a meaningful projection
        if days_elapsed < 5:
            return
        days_in_month = (
            (first_of_month.replace(month=first_of_month.month % 12 + 1, day=1)
             if first_of_month.month < 12
             else first_of_month.replace(year=first_of_month.year + 1, month=1, day=1))
            - first_of_month
        ).days

        # Spending so far this month
        txns = await repo.get_transactions(since_date=first_of_month.isoformat(), limit=1000)
        debits = [t for t in txns if t['amount'] > 0]
        spending_so_far = sum(t['amount'] for t in debits)

        # Average monthly spending from last 3 months
        monthly = await repo.get_monthly_spending(months=3)
        if not monthly:
            return
        avg_monthly = sum(m['spending'] for m in monthly) / len(monthly)

        # Calculate pace
        projected = (spending_so_far / days_elapsed) * days_in_month

        if projected > avg_monthly * 1.2:
            await ctx.bot.send_message(
                f"Spending pace alert: You've spent ${spending_so_far:,.2f} in {days_elapsed} days. "
                f"At this rate you'll hit ${projected:,.2f} this month (avg is ${avg_monthly:,.2f})."
            )

    await _retry(_do_pace, ctx, source="spending_pace_check")


async def job_weekly_digest(ctx) -> None:
    """Saturday at 9am — weekly spending digest."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_digest():
        import datetime
        from collections import defaultdict
        from pa.plugins.finance.repository import FinanceRepository
        from pa.plugins.finance.advisor import load_profile

        repo = FinanceRepository(ctx.store)
        today = datetime.date.today()

        # This week (Mon–today) and last week
        days_since_monday = today.weekday()
        this_monday = today - datetime.timedelta(days=days_since_monday)
        last_monday = this_monday - datetime.timedelta(days=7)

        # This week's transactions
        this_week_txns = await repo.get_transactions(
            since_date=this_monday.isoformat(), limit=500
        )
        this_week_debits = [
            t for t in this_week_txns
            if t['amount'] > 0 and t['date'] >= this_monday.isoformat()
        ]
        this_week_total = sum(t['amount'] for t in this_week_debits)

        # Last week's transactions
        last_week_txns = await repo.get_transactions(
            since_date=last_monday.isoformat(), limit=500
        )
        last_week_debits = [
            t for t in last_week_txns
            if t['amount'] > 0
            and last_monday.isoformat() <= t['date'] < this_monday.isoformat()
        ]
        last_week_total = sum(t['amount'] for t in last_week_debits)

        # Top 3 categories this week
        by_cat = defaultdict(float)
        for t in this_week_debits:
            cat = t.get('category') or 'Uncategorized'
            by_cat[cat.split('/')[0]] += t['amount']
        top_cats = sorted(by_cat.items(), key=lambda x: -x[1])[:3]

        parts = [
            f"Weekly Digest ({this_monday.isoformat()} to {today.isoformat()})",
            "",
            f"Total spending: ${this_week_total:,.2f}",
        ]

        if last_week_total > 0:
            diff = this_week_total - last_week_total
            direction = "up" if diff > 0 else "down"
            parts.append(
                f"vs last week: ${last_week_total:,.2f} ({direction} ${abs(diff):,.2f})"
            )

        if top_cats:
            parts.append("")
            parts.append("Top categories:")
            for cat, amt in top_cats:
                parts.append(f"  - {cat}: ${amt:,.2f}")

        # Bills paid this week
        bills_paid = await ctx.store.fetchall(
            "SELECT name, amount FROM finance_bills WHERE last_paid >= ?",
            (this_monday.isoformat(),),
        )
        if bills_paid:
            parts.append("")
            parts.append("Bills paid:")
            for b in bills_paid:
                parts.append(f"  - {b['name']}: ${b['amount'] or 0:,.2f}")

        # Bills due next week
        next_monday = this_monday + datetime.timedelta(days=7)
        next_sunday = this_monday + datetime.timedelta(days=13)
        bills_due = await ctx.store.fetchall(
            "SELECT name, amount, due_date FROM finance_bills "
            "WHERE paid_this_cycle = 0 AND due_date >= ? AND due_date <= ? "
            "ORDER BY due_date",
            (next_monday.isoformat(), next_sunday.isoformat()),
        )
        if bills_due:
            parts.append("")
            parts.append("Bills due next week:")
            for b in bills_due:
                parts.append(
                    f"  - {b['name']}: ${b['amount'] or 0:,.2f} (due {b['due_date']})"
                )

        # Subscription total
        profile = await load_profile(ctx)
        sub_total = profile.get('subscription_total', 0)
        if sub_total and sub_total > 50:
            parts.append("")
            parts.append(f"Monthly subscriptions: ${sub_total:,.2f}")

        await ctx.bot.send_message("\n".join(parts))

    await _retry(_do_digest, ctx, source="weekly_digest")


async def job_budget_nag(ctx) -> None:
    """3x daily budget check — pure SQL, zero API calls.
    Checks each budget category and nags if approaching or over limit."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_nag():
        import datetime
        today = datetime.date.today()
        month = today.strftime('%Y-%m')
        day = today.day

        budgets = await ctx.store.fetchall("SELECT * FROM finance_budgets")
        if not budgets:
            return

        alerts = []
        for b in budgets:
            cat = b['category']
            limit = b['monthly_limit']
            alert_pct = b.get('alert_at_pct', 0.8)

            row = await ctx.store.fetchone(
                """SELECT COALESCE(SUM(amount), 0) AS spent
                   FROM finance_transactions
                   WHERE amount > 0 AND category = ? AND strftime('%Y-%m', date) = ?""",
                (cat, month),
            )
            spent = row['spent'] if row else 0
            pct = spent / limit if limit > 0 else 0

            # Determine alert type
            if pct >= 1.0:
                alert_type = "over"
                msg = f"🔴 {cat}: ${spent:,.0f} / ${limit:,.0f} — OVER BUDGET by ${spent - limit:,.0f}"
            elif pct >= alert_pct:
                alert_type = "warning"
                remaining = limit - spent
                # Calculate how many days left and daily allowance
                if today.month == 12:
                    month_end = datetime.date(today.year + 1, 1, 1)
                else:
                    month_end = datetime.date(today.year, today.month + 1, 1)
                days_left = (month_end - today).days
                daily = remaining / days_left if days_left > 0 else 0
                msg = f"🟡 {cat}: ${spent:,.0f} / ${limit:,.0f} ({pct:.0%}) — ${remaining:,.0f} left = ~${daily:,.0f}/day"
            else:
                continue

            # Deduplicate: only send each alert type once per day
            already = await ctx.store.fetchone(
                """SELECT 1 FROM finance_budget_alerts
                   WHERE category = ? AND month = ? AND alert_type = ?
                   AND date(sent_at) = date('now')""",
                (cat, month, alert_type),
            )
            if already:
                continue

            await ctx.store.execute(
                """INSERT INTO finance_budget_alerts (category, month, alert_type)
                   VALUES (?, ?, ?)
                   ON CONFLICT(category, month, alert_type) DO UPDATE SET sent_at=CURRENT_TIMESTAMP""",
                (cat, month, alert_type),
            )
            alerts.append(msg)

        if alerts:
            header = "**Bart's Budget Check**\n" if len(alerts) > 1 else ""
            await ctx.bot.send_message(header + "\n".join(alerts))

    await _retry(_do_nag, ctx, source="budget_nag")


async def job_bart_daily_nag(ctx) -> None:
    """Evening nag from Bart — pure SQL, zero API calls.
    Summarizes today's damage and reminds about upcoming obligations."""
    if not ctx.vault.is_unlocked:
        return

    async def _do_nag():
        import datetime
        from pa.plugins.finance.repository import FinanceRepository
        repo = FinanceRepository(ctx.store)

        today = datetime.date.today().isoformat()
        month = datetime.date.today().strftime('%Y-%m')

        # Today's spending
        txns = await repo.get_transactions(since_date=today, limit=200)
        today_debits = [t for t in txns if t['date'] == today and t['amount'] > 0]
        today_total = sum(t['amount'] for t in today_debits)

        # Month-to-date spending
        row = await ctx.store.fetchone(
            """SELECT COALESCE(SUM(amount), 0) AS spent
               FROM finance_transactions
               WHERE amount > 0 AND strftime('%Y-%m', date) = ?""",
            (month,),
        )
        mtd = row['spent'] if row else 0

        # Total budget
        budget_row = await ctx.store.fetchone(
            "SELECT COALESCE(SUM(monthly_limit), 0) AS total FROM finance_budgets"
        )
        total_budget = budget_row['total'] if budget_row else 0

        # Checking balance
        balances = await repo.get_latest_balances()
        checking = sum(b['balance'] for b in balances if b['type'] in ('checking', 'depository'))

        # Unpaid bills
        upcoming = await ctx.store.fetchall(
            """SELECT name, amount, due_date FROM finance_bills
               WHERE paid_this_cycle = 0 AND due_date IS NOT NULL
               ORDER BY due_date LIMIT 5"""
        )
        bills_total = sum(b['amount'] or 0 for b in upcoming)

        parts = ["**Bart's Evening Report**\n"]

        if today_total > 0:
            top_txns = sorted(today_debits, key=lambda t: t['amount'], reverse=True)[:3]
            txn_list = ", ".join(f"{t['description'][:20]} ${t['amount']:,.0f}" for t in top_txns)
            parts.append(f"Today: ${today_total:,.2f} spent ({txn_list})")
        else:
            parts.append("Today: $0 spent — nice discipline.")

        if total_budget > 0:
            remaining = total_budget - mtd
            pct = mtd / total_budget * 100
            if remaining > 0:
                parts.append(f"Month: ${mtd:,.0f} / ${total_budget:,.0f} budget ({pct:.0f}%) — ${remaining:,.0f} left")
            else:
                parts.append(f"Month: ${mtd:,.0f} / ${total_budget:,.0f} — ⚠️ OVER by ${abs(remaining):,.0f}")

        parts.append(f"Checking: ${checking:,.2f}")

        if upcoming:
            bill_lines = [f"  {b['name']}: ${b['amount'] or 0:,.0f} due {b['due_date']}" for b in upcoming[:3]]
            parts.append(f"Next bills (${bills_total:,.0f} total):\n" + "\n".join(bill_lines))

        available = checking - bills_total
        if available < 200:
            parts.append(f"\n⚠️ After bills you'll have ~${available:,.0f}. Watch it.")
        elif available < 500:
            parts.append(f"\nAfter bills: ~${available:,.0f}. Tight but manageable.")

        await ctx.bot.send_message("\n".join(parts))

    await _retry(_do_nag, ctx, source="bart_daily_nag")


def get_finance_jobs() -> list[Job]:
    return [
        Job(name="morning_sync", handler=job_morning_sync,
            trigger="cron", kwargs={"hour": 7, "minute": 0}),
        Job(name="balance_check", handler=job_balance_check,
            trigger="interval", kwargs={"hours": 4}),
        Job(name="due_date_check", handler=job_due_date_check,
            trigger="cron", kwargs={"hour": 8, "minute": 0}),
        Job(name="bill_reminders", handler=job_bill_reminders,
            trigger="cron", kwargs={"hour": 8, "minute": 30}),
        Job(name="weekly_advisor", handler=job_weekly_advisor,
            trigger="cron", kwargs={"day_of_week": "sun", "hour": 8, "minute": 0}),
        Job(name="spending_pace_check", handler=job_spending_pace_check,
            trigger="cron", kwargs={"hour": 12, "minute": 0}),
        Job(name="weekly_digest", handler=job_weekly_digest,
            trigger="cron", kwargs={"day_of_week": "sat", "hour": 9, "minute": 0}),
        Job(name="budget_nag_morning", handler=job_budget_nag,
            trigger="cron", kwargs={"hour": 9, "minute": 0}),
        Job(name="budget_nag_afternoon", handler=job_budget_nag,
            trigger="cron", kwargs={"hour": 15, "minute": 0}),
        Job(name="bart_evening_report", handler=job_bart_daily_nag,
            trigger="cron", kwargs={"hour": 20, "minute": 0}),
    ]
