"""Natural language handler for finance plugin."""
from __future__ import annotations
from telegram import Update
from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_finance_nl(ctx: AppContext, text: str, update: Update) -> str:
    from pa.plugins.finance.repository import FinanceRepository
    tl = text.lower()
    repo = FinanceRepository(ctx.store)

    # Merchant category corrections: "X is a Y" or "X is not Y"
    if any(phrase in tl for phrase in [
        " is a ", " is an ", " is not ", " isn't ", " isnt ",
        "categorize ", "that's actually", "thats actually",
    ]):
        from pa.plugins.finance.merchants import learn_category
        # Use Haiku to parse the correction
        PARSE = """Parse this merchant categorization correction. Return ONLY JSON:
{"merchant":"merchant name","category":"correct category","action":"set"|"unclear"}
If unclear: {"action":"unclear"}. Raw JSON only."""
        result = await ctx.brain.query(text, system_prompt=PARSE, tier=Tier.FAST, use_conversation=False)
        try:
            import json, re
            result = re.sub(r',\s*([}\]])', r'\1', result.strip())
            start = result.find('{')
            end = result.rfind('}')
            if start != -1:
                data = json.loads(result[start:end+1])
                if data.get('action') == 'set' and data.get('merchant') and data.get('category'):
                    await learn_category(ctx.store, data['merchant'], data['category'], source="user")
                    return f"Got it — '{data['merchant']}' is now categorized as '{data['category']}'. I'll remember that."
        except Exception:
            pass
        return "I couldn't parse that correction. Try: 'Hilltop Liquors is a liquor store' or 'Cleo is a cash advance app'"

    # Manual payment/balance updates
    if any(phrase in tl for phrase in [
        "i paid", "i just paid", "paid off", "made a payment",
        "balance is now", "balance is", "updated balance", "new balance",
    ]):
        from pa.plugins.finance.advisor import handle_manual_update
        return await handle_manual_update(ctx, text)

    if any(w in tl for w in ["balance", "how much", "account", "checking", "savings", "credit card"]):
        balances = await repo.get_latest_balances()
        if not balances:
            return "No account data yet. Use /sync to fetch your balances."
        data_summary = "\n".join(
            f"{b['institution']} {b['name']} ({b['type']}): ${b['balance']:,.2f}"
            for b in balances
        )
        prompt = f"User asked: '{text}'\n\nCurrent balances:\n{data_summary}\n\nAnswer directly."
        return await ctx.brain.query(prompt, tier=Tier.FAST, use_conversation=False)

    elif any(w in tl for w in ["debt", "owe", "loan", "mortgage", "payoff"]):
        balances = await repo.get_latest_balances()
        debts = [b for b in balances if b['type'] in ('credit_card', 'loan', 'mortgage', 'credit')]
        # Also get manually tracked debts
        stored = await ctx.store.fetchall(
            "SELECT * FROM finance_debts ORDER BY balance DESC"
        ) if True else []
        if not debts and not stored:
            return "No debt accounts found. Use /sync to fetch your data."
        lines = []
        for d in debts:
            line = f"{d['institution']} {d['name']}: ${d['balance']:,.2f}"
            if d.get('interest_rate'):
                line += f" @ {d['interest_rate']:.1f}% APR"
            lines.append(line)
        for d in stored:
            line = f"{d['institution']} {d['account_name']}: ${d['balance']:,.2f} [{d['status']}]"
            if d.get('apr'):
                line += f" @ {d['apr']:.1f}%"
            lines.append(line)
        total = sum(d['balance'] for d in debts) + sum(d['balance'] for d in stored)
        data_summary = "\n".join(lines)
        prompt = f"User asked: '{text}'\n\nDebt accounts (total ${total:,.2f}):\n{data_summary}\n\nBe specific. Give actionable advice."
        return await ctx.brain.query(prompt, tier=Tier.FAST, use_conversation=False)

    elif any(w in tl for w in ["spending", "spent", "expenses", "transactions", "charges", "subscription"]):
        import datetime
        since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        txns = await repo.get_transactions(since_date=since, limit=50)
        if not txns:
            return "No transaction data yet. Use /sync to fetch."
        debits = [t for t in txns if t['amount'] > 0]
        total = sum(t['amount'] for t in debits)
        lines = "\n".join(
            f"{t['date']} {t['description'][:35]}: ${t['amount']:,.2f}"
            for t in debits[:20]
        )
        prompt = f"User asked: '{text}'\n\nLast 30 days spending (total ${total:,.2f}):\n{lines}\n\nIdentify patterns, subscriptions, and areas to cut."
        return await ctx.brain.query(prompt, tier=Tier.FAST, use_conversation=False)

    elif any(w in tl for w in ["due", "payment", "bill", "upcoming"]):
        balances = await repo.get_latest_balances()
        due = [b for b in balances if b.get('due_date') or b.get('minimum_payment')]
        if not due:
            return "No upcoming payment data. Try /sync or /advisor."
        data_summary = "\n".join(
            f"{d['institution']} {d['name']}: "
            + (f"${d['minimum_payment']:,.2f} due {d['due_date']}" if d.get('due_date') else f"${d['balance']:,.2f}")
            for d in due
        )
        prompt = f"User asked: '{text}'\n\nUpcoming payments:\n{data_summary}\n\nAnswer clearly, flag anything urgent."
        return await ctx.brain.query(prompt, tier=Tier.FAST, use_conversation=False)

    else:
        return "Try asking about your balances, debt, spending, or upcoming bills. Say 'I paid X on Y' to record a payment. Or use /advisor for a full analysis."
