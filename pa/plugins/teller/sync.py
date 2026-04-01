"""Syncs Teller account data into pa.db."""
from __future__ import annotations
import datetime
from pa.plugins.teller.client import TellerClient
from pa.plugins.finance.repository import FinanceRepository


async def sync_teller_accounts(ctx, institutions=None):
    client = TellerClient(ctx.vault)
    repo = FinanceRepository(ctx.store)
    messages = []
    tokens = {
        k.replace('teller_', ''): v.get('access_token')
        for k, v in ctx.vault._data.items()
        if k.startswith('teller_') and isinstance(v, dict) and 'access_token' in v
    }
    if not tokens:
        return ["No Teller accounts connected."]
    for inst_name, token in tokens.items():
        if institutions and inst_name not in institutions:
            continue
        try:
            accounts = client.get_accounts(token)
            synced = 0
            for acct in accounts:
                try:
                    bal_data = client.get_balances(token, acct['id'])
                    # For checking/savings use available (spendable), for credit use ledger (owed)
                    acct_type = acct.get('type', '')
                    if acct_type == 'depository':
                        balance = float(bal_data.get('available') or bal_data.get('ledger') or 0)
                    else:
                        balance = float(bal_data.get('ledger') or bal_data.get('available') or 0)
                except Exception:
                    balance = 0.0
                existing = await repo.get_accounts()
                existing_map = {(a['institution'], a['name']): a['id'] for a in existing}
                key = (acct['institution']['name'], acct['name'])
                if key in existing_map:
                    account_id = existing_map[key]
                else:
                    account_id = await repo.add_account(
                        institution=acct['institution']['name'],
                        name=acct['name'],
                        account_type=acct.get('subtype', acct.get('type', 'checking')),
                    )
                await repo.add_balance(account_id=account_id, balance=balance)
                try:
                    txns = client.get_transactions(token, acct['id'], count=50)
                    for t in txns:
                        amount = abs(float(t.get('amount', 0)))
                        if t.get('type') == 'credit':
                            amount = -amount
                        await repo.add_transaction(
                            account_id=account_id,
                            date=t.get('date', ''),
                            description=t.get('description', ''),
                            amount=amount,
                            posted_date=t.get('date'),
                            category=t.get('details', {}).get('category'),
                        )
                except Exception:
                    pass
                synced += 1
            messages.append(f"{inst_name}: synced {synced} account(s) ✓")
        except Exception as e:
            messages.append(f"{inst_name}: failed — {e}")
    return messages


async def get_spending_by_merchant(ctx, merchant, days=30):
    from pa.core.tier import Tier
    from pa.plugins.finance.merchants import categorize_transactions
    repo = FinanceRepository(ctx.store)
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=500)
    # Fuzzy match: all words in merchant name must appear in the description
    merchant_words = merchant.lower().split()
    matches = [
        t for t in txns
        if all(w in t['description'].lower() for w in merchant_words) and t['amount'] > 0
    ]
    if not matches:
        return f"I find no record of spending at {merchant} in the last {days} days."
    await categorize_transactions(ctx.store, matches)
    total = sum(t['amount'] for t in matches)
    lines = "\n".join(
        f"  {t['date']}: ${t['amount']:,.2f} [{t.get('learned_category') or 'Uncategorized'}]"
        for t in matches
    )
    prompt = f"Steven asked about spending at '{merchant}' over {days} days.\nFound {len(matches)} transactions totaling ${total:,.2f}:\n{lines}\nGive a brief Dumbledore-style summary. Be honest if the amount is concerning."
    return await ctx.brain.query(prompt, tier=Tier.FAST, use_conversation=False)


async def get_weekly_spending_summary(ctx):
    from pa.core.tier import Tier
    from pa.plugins.finance.merchants import categorize_transactions
    repo = FinanceRepository(ctx.store)
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=200)
    debits = [t for t in txns if t['amount'] > 0]
    if not debits:
        return "No transactions found for the past week."
    await categorize_transactions(ctx.store, debits)
    total = sum(t['amount'] for t in debits)
    # Group by learned category
    by_cat: dict[str, list] = {}
    for t in debits:
        cat = t.get('learned_category') or 'Uncategorized'
        by_cat.setdefault(cat, []).append(t)
    cat_summary = "\n".join(
        f"  {cat}: ${sum(t['amount'] for t in items):,.2f} ({len(items)} txns)"
        for cat, items in sorted(by_cat.items(), key=lambda x: -sum(t['amount'] for t in x[1]))
    )
    txn_list = "\n".join(
        f"{t['date']} | {t['description'][:45]} | ${t['amount']:,.2f} | {t.get('learned_category') or 'Uncategorized'}"
        for t in debits
    )
    prompt = (
        f"Analyze Steven's spending for the past 7 days. Total: ${total:,.2f}\n\n"
        f"Spending by category:\n{cat_summary}\n\n"
        f"Transactions:\n{txn_list}\n\n"
        f"Categories are pre-assigned above — use them as-is.\n"
        f"1. Show the category breakdown (already provided)\n"
        f"2. Flag concerning patterns\n"
        f"3. Give 2-3 actionable insights\n"
        f"Speak as Dumbledore. Keep it readable."
    )
    return await ctx.brain.query(prompt, tier=Tier.FAST, use_conversation=False)


async def get_yesterday_summary(ctx):
    from pa.core.tier import Tier
    from pa.plugins.finance.merchants import categorize_transactions
    repo = FinanceRepository(ctx.store)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    balances = await repo.get_latest_balances()
    wf_balances = [b for b in balances if 'wells' in b['institution'].lower()]
    txns = await repo.get_transactions(since_date=yesterday, limit=100)
    yesterday_txns = [t for t in txns if t['date'] == yesterday and t['amount'] > 0]
    if not wf_balances and not yesterday_txns:
        return None
    balance_str = "\n".join(f"{b['name']}: ${b['balance']:,.2f}" for b in wf_balances) if wf_balances else "No balance data"
    if yesterday_txns:
        await categorize_transactions(ctx.store, yesterday_txns)
        total = sum(t['amount'] for t in yesterday_txns)
        txn_lines = "\n".join(
            f"  {t['description'][:35]}: ${t['amount']:,.2f} [{t.get('learned_category') or 'Uncategorized'}]"
            for t in yesterday_txns[:10]
        )
        txn_str = f"Yesterday's spending (${total:,.2f} total):\n{txn_lines}"
    else:
        txn_str = "No spending yesterday."
    prompt = f"Give Steven a brief friendly morning financial update.\n\nWells Fargo balances:\n{balance_str}\n\n{txn_str}\n\nKeep it to 3-4 sentences. Speak like Dumbledore. Flag anything concerning."
    return await ctx.brain.query(prompt, tier=Tier.FAST, use_conversation=False)
