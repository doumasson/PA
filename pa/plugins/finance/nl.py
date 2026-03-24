"""Natural language handler for finance plugin."""
from __future__ import annotations
from telegram import Update
from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_finance_nl(ctx: AppContext, text: str, update: Update) -> str:
    from pa.plugins.finance.repository import FinanceRepository
    tl = text.lower()
    repo = FinanceRepository(ctx.store)

    if any(w in tl for w in ["balance", "how much", "account", "checking", "savings", "credit card"]):
        balances = await repo.get_latest_balances()
        if not balances:
            return "No account data yet. Use /scrape to fetch your balances."
        data_summary = "\n".join(
            f"{b['institution']} {b['name']} ({b['type']}): ${b['balance']:,.2f}"
            for b in balances
        )
        prompt = f"User asked: '{text}'\n\nCurrent balances:\n{data_summary}\n\nAnswer directly and helpfully."

    elif any(w in tl for w in ["debt", "owe", "loan", "mortgage", "payoff"]):
        balances = await repo.get_latest_balances()
        debts = [b for b in balances if b['type'] in ('credit_card', 'loan', 'mortgage', 'credit')]
        if not debts:
            return "No debt accounts found. Use /scrape to fetch your data."
        data_summary = "\n".join(
            f"{d['institution']} {d['name']}: ${d['balance']:,.2f}"
            + (f" @ {d['interest_rate']:.1f}% APR" if d.get('interest_rate') else "")
            for d in debts
        )
        total = sum(d['balance'] for d in debts)
        prompt = f"User asked: '{text}'\n\nDebt accounts (total ${total:,.2f}):\n{data_summary}\n\nBe specific with numbers and give actionable advice."

    elif any(w in tl for w in ["spending", "spent", "expenses", "transactions", "charges"]):
        import datetime
        since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        txns = await repo.get_transactions(since_date=since, limit=50)
        if not txns:
            return "No transaction data yet. Use /scrape to fetch your transactions."
        debits = [t for t in txns if t['amount'] > 0]
        total = sum(t['amount'] for t in debits)
        lines = "\n".join(
            f"{t['date']} {t['description'][:35]}: ${t['amount']:,.2f}"
            for t in debits[:20]
        )
        prompt = f"User asked: '{text}'\n\nLast 30 days spending (total ${total:,.2f}):\n{lines}\n\nGive specific insights and flag any concerns."

    elif any(w in tl for w in ["due", "payment", "bill", "upcoming"]):
        balances = await repo.get_latest_balances()
        due = [b for b in balances if b.get('due_date') or b.get('minimum_payment')]
        if not due:
            return "No upcoming payment data available. Use /scrape to fetch your data."
        data_summary = "\n".join(
            f"{d['institution']} {d['name']}: "
            + (f"${d['minimum_payment']:,.2f} due {d['due_date']}" if d.get('due_date') else f"${d['balance']:,.2f} balance")
            for d in due
        )
        prompt = f"User asked: '{text}'\n\nUpcoming payments:\n{data_summary}\n\nAnswer clearly, flag anything urgent."

    else:
        return "Try asking about your balances, debt, spending, or upcoming payments. Or use /balance, /debt, /spending, /due."

    return await ctx.brain.query(prompt, tier=Tier.STANDARD)
