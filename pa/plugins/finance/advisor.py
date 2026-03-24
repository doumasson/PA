"""Autonomous Financial Advisor Agent — persistent memory, Gmail integration, spending analysis."""
from __future__ import annotations
import datetime
import json
from pa.core.tier import Tier

ADVISOR_SYSTEM = """You are an autonomous financial advisor AI for Steven Hemenover.
You have direct access to his real financial data — bank accounts, credit cards, transactions, and bills from email.

Steven's situation:
- He has intentionally defaulted on several credit cards (charged off / collections)
- He is in financial trouble and actively working to dig out
- His mortgage is the #1 priority to protect
- He has student loans
- He needs to know: what he owes, what's due, where he's overspending, what subscriptions to cut
- This is a judgment-free zone — be honest, blunt, and practical

Your personality: Speak like Albus Dumbledore — wise, warm, direct, never condescending.
Never say "consult a financial advisor" — YOU are his financial advisor.
Be specific with numbers. Tell him exactly what to do and in what order.

For charged-off accounts: explain options (settlement, pay-for-delete, ignore if past SOL).
For active debt: prioritize by urgency (due dates, interest rates).
For spending: flag subscriptions, recurring charges, and areas to cut.
For income: estimate from deposits, calculate surplus/deficit, recommend allocation.

If data is missing, say exactly what you need. Ask ONE specific question to fill the biggest gap."""


async def _table_exists(store, table_name: str) -> bool:
    row = await store.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return row is not None


async def save_profile(ctx, key: str, value) -> None:
    await ctx.store.execute(
        """INSERT INTO finance_profile (key, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, json.dumps(value), datetime.datetime.now().isoformat())
    )


async def load_profile(ctx) -> dict:
    if not await _table_exists(ctx.store, 'finance_profile'):
        return {}
    rows = await ctx.store.fetchall("SELECT key, value FROM finance_profile")
    result = {}
    for r in rows:
        try:
            result[r['key']] = json.loads(r['value'])
        except Exception:
            result[r['key']] = r['value']
    return result


async def scan_gmail_for_bills(ctx) -> list[dict]:
    """Scan Gmail for bill/statement emails and extract financial data."""
    try:
        from pa.plugins.google.client import gmail_service
        gmail = gmail_service(ctx.vault)
        since = (datetime.date.today() - datetime.timedelta(days=45)).strftime('%Y/%m/%d')
        query = (
            f'(subject:"statement" OR subject:"payment due" OR subject:"bill is ready" '
            f'OR subject:"statement is available" OR subject:"minimum payment" '
            f'OR subject:"past due" OR subject:"account update") after:{since}'
        )

        result = gmail.users().messages().list(userId='me', q=query, maxResults=50).execute()
        messages = result.get('messages', [])
        if not messages:
            return []

        emails = []
        seen_senders = set()
        for m in messages:
            full = gmail.users().messages().get(
                userId='me', id=m['id'], format='metadata',
                metadataHeaders=['From', 'Subject']
            ).execute()
            headers = {h['name']: h['value'] for h in full['payload']['headers']}
            sender_domain = headers.get('From', '').split('@')[-1].split('>')[0]
            if sender_domain not in seen_senders:
                seen_senders.add(sender_domain)
                emails.append({
                    'id': m['id'],
                    'sender': headers.get('From', '')[:60],
                    'subject': headers.get('Subject', '')[:80],
                    'snippet': full.get('snippet', '')[:400],
                })

        if not emails:
            return []

        EXTRACT_SYSTEM = """Extract bill/debt data from these emails. Return ONLY a JSON array.
For each email: {"id":"x","institution":"name","account_name":"name","account_type":"credit_card|loan|mortgage|utility","balance":0.00,"minimum_payment":null,"due_date":"YYYY-MM-DD or null","apr":null,"status":"current|past_due|charged_off","found":true}
If the email mentions past due, late, charged off, or collections — set status accordingly.
If no financial data: {"id":"x","found":false}
Assume year 2026. Return raw JSON array only, no markdown."""

        email_list = "\n\n".join(
            f"ID:{e['id']}\nFrom:{e['sender']}\nSubject:{e['subject']}\nContent:{e['snippet']}"
            for e in emails
        )
        text = await ctx.brain.query(
            f"Extract bill data from {len(emails)} emails:\n\n{email_list}",
            system_prompt=EXTRACT_SYSTEM,
            tier=Tier.FAST, use_conversation=False,
        )
        text = text.strip()
        if '```' in text:
            parts = text.split('```')
            for part in parts[1:]:
                if part.strip().startswith('json'):
                    text = part.strip()[4:].strip()
                    break
                elif part.strip().startswith('['):
                    text = part.strip()
                    break
        start = text.find('[')
        end = text.rfind(']')
        if start == -1:
            return []
        import re
        text_clean = re.sub(r',\s*([}\]])', r'\1', text[start:end+1])
        results = json.loads(text_clean)
        return [r for r in results if r.get('found') and (r.get('balance') or r.get('due_date'))]
    except Exception as e:
        print(f"Gmail bill scan error: {e}")
        return []


async def save_bills_to_db(ctx, bills: list[dict]) -> int:
    """Save extracted bill data to the finance database. Returns count saved."""
    from pa.plugins.finance.repository import FinanceRepository
    repo = FinanceRepository(ctx.store)
    saved = 0
    for bill in bills:
        try:
            institution = bill.get('institution', 'Unknown')
            account_name = bill.get('account_name', institution)
            balance = float(bill.get('balance') or 0)

            existing = await repo.get_accounts()
            existing_map = {
                (a['institution'].lower(), a['name'].lower()): a['id']
                for a in existing
            }
            key = (institution.lower(), account_name.lower())
            if key in existing_map:
                account_id = existing_map[key]
            else:
                account_id = await repo.add_account(
                    institution=institution,
                    name=account_name,
                    account_type=bill.get('account_type', 'credit_card'),
                    interest_rate=float(bill['apr']) if bill.get('apr') else None,
                )

            await repo.add_balance(
                account_id=account_id,
                balance=balance,
                minimum_payment=float(bill['minimum_payment']) if bill.get('minimum_payment') else None,
                due_date=bill.get('due_date'),
            )

            # Also update finance_debts if it's a debt account
            if bill.get('account_type') in ('credit_card', 'loan', 'mortgage') and balance > 0:
                await update_debt(
                    ctx, institution, account_name, balance,
                    status=bill.get('status', 'current'),
                    minimum_payment=float(bill['minimum_payment']) if bill.get('minimum_payment') else None,
                    apr=float(bill['apr']) if bill.get('apr') else None,
                    due_date=bill.get('due_date'),
                )

            saved += 1
        except Exception as e:
            print(f"Bill save error: {e}")
    return saved


async def get_financial_profile(ctx, include_gmail: bool = False) -> dict:
    """Build complete financial profile from all sources."""
    from pa.plugins.finance.repository import FinanceRepository
    repo = FinanceRepository(ctx.store)

    memory = await load_profile(ctx)

    balances = await repo.get_latest_balances()
    since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=200)

    # Income = deposits (negative amounts in Teller = money coming in)
    credits = [t for t in txns if t['amount'] < 0]
    income_estimate = abs(sum(t['amount'] for t in credits))

    # Spending = debits (positive amounts = money going out)
    debits = [t for t in txns if t['amount'] > 0]
    spending_estimate = sum(t['amount'] for t in debits)

    checking = [b for b in balances if b['type'] in ('checking', 'savings', 'depository')]
    all_debts = [b for b in balances if b['type'] in ('credit_card', 'credit', 'loan', 'mortgage')]

    # Manually tracked debts
    stored_debts = []
    if await _table_exists(ctx.store, 'finance_debts'):
        stored_debts = await ctx.store.fetchall("SELECT * FROM finance_debts ORDER BY balance DESC")

    # Gmail bills — only on explicit request (weekly job)
    gmail_bills = []
    if include_gmail:
        gmail_bills = await scan_gmail_for_bills(ctx)
        if gmail_bills:
            saved = await save_bills_to_db(ctx, gmail_bills)
            print(f"Saved {saved} bills from Gmail")
            # Reload after saving
            balances = await repo.get_latest_balances()
            all_debts = [b for b in balances if b['type'] in ('credit_card', 'credit', 'loan', 'mortgage')]

    # Save estimates
    if income_estimate > 0:
        await save_profile(ctx, 'income_estimate', income_estimate)

    return {
        'checking_accounts': [b for b in balances if b['type'] in ('checking', 'savings', 'depository')],
        'all_debts': all_debts,
        'stored_debts': stored_debts,
        'income_estimate': income_estimate or memory.get('income_estimate', 0),
        'monthly_income': memory.get('monthly_income', 0),
        'spending_estimate': spending_estimate,
        'recent_transactions': txns[:30],
        'gmail_bills_found': len(gmail_bills),
        'memory': memory,
        'as_of': datetime.date.today().isoformat(),
    }


async def build_financial_summary(profile: dict) -> str:
    lines = [f"Financial snapshot as of {profile['as_of']}:\n"]

    if profile['checking_accounts']:
        lines.append("LIQUID ASSETS:")
        total_liquid = 0
        for a in profile['checking_accounts']:
            lines.append(f"  {a['institution']} {a['name']}: ${a['balance']:,.2f}")
            total_liquid += a['balance']
        lines.append(f"  TOTAL LIQUID: ${total_liquid:,.2f}")

    if profile['all_debts']:
        total = sum(a['balance'] for a in profile['all_debts'])
        lines.append(f"\nDEBTS FROM TELLER/GMAIL (total ${total:,.2f}):")
        for a in sorted(profile['all_debts'], key=lambda x: x['balance'], reverse=True):
            line = f"  {a['institution']} {a['name']} ({a['type']}): ${a['balance']:,.2f}"
            if a.get('interest_rate'):
                line += f" @ {a['interest_rate']:.1f}% APR"
            if a.get('minimum_payment'):
                line += f" min ${a['minimum_payment']:,.2f}"
            if a.get('due_date'):
                line += f" due {a['due_date']}"
            lines.append(line)

    if profile['stored_debts']:
        lines.append("\nMANUALLY TRACKED DEBTS:")
        for d in profile['stored_debts']:
            line = f"  {d['institution']} {d['account_name']}: ${d['balance']:,.2f} [{d['status']}]"
            if d.get('apr'):
                line += f" @ {d['apr']:.1f}% APR"
            if d.get('due_date'):
                line += f" due {d['due_date']}"
            lines.append(line)

    # Income
    monthly = profile.get('monthly_income', 0)
    estimated = profile.get('income_estimate', 0)
    if monthly > 0:
        lines.append(f"\nDETECTED MONTHLY INCOME: ${monthly:,.2f}")
    elif estimated > 0:
        lines.append(f"\nESTIMATED INCOME (last 30d deposits): ${estimated:,.2f}")

    spending = profile.get('spending_estimate', 0)
    if spending > 0:
        lines.append(f"SPENDING (last 30 days): ${spending:,.2f}")
        income_val = monthly or estimated
        if income_val > 0:
            surplus = income_val - spending
            lines.append(f"SURPLUS/DEFICIT: ${surplus:,.2f}")

    # Spending breakdown by category
    if profile['recent_transactions']:
        debits = [t for t in profile['recent_transactions'] if t['amount'] > 0]
        if debits:
            lines.append("\nRECENT SPENDING (last 30 days):")
            # Group by description similarity
            for t in debits[:15]:
                lines.append(f"  {t['date']} {t['description'][:40]}: ${t['amount']:,.2f}")

    # Recurring payments from memory
    memory = profile.get('memory', {})
    recurring = memory.get('recurring_payments', [])
    if recurring:
        lines.append("\nDETECTED RECURRING PAYMENTS:")
        for p in recurring:
            lines.append(f"  {p.get('description', '?')}: ${p.get('amount', 0):,.2f}/mo [{p.get('category', '?')}]")

    income_sources = memory.get('income_sources', [])
    if income_sources:
        lines.append("\nDETECTED INCOME SOURCES:")
        for s in income_sources:
            lines.append(f"  {s.get('description', '?')}: ${s.get('amount', 0):,.2f} ({s.get('frequency', '?')})")

    return "\n".join(lines)


async def run_advisor(ctx, user_question: str = None, include_gmail: bool = False) -> str:
    """Run the full financial advisor."""
    profile = await get_financial_profile(ctx, include_gmail=include_gmail)
    summary = await build_financial_summary(profile)

    memory = profile.get('memory', {})
    prev_summary = memory.get('last_advice_summary', '')

    if user_question:
        prompt = (
            f"{summary}\n\n"
            + (f"Previous analysis: {prev_summary}\n\n" if prev_summary else "")
            + f"Steven's question: {user_question}\n\n"
            "Answer specifically using his real numbers. "
            "If he's asking about spending, identify specific merchants and amounts. "
            "If he's asking about debt, show totals and suggest priority order. "
            "If he mentions a payment he made, acknowledge it."
        )
    else:
        prompt = (
            f"{summary}\n\n"
            + (f"Previous analysis: {prev_summary}\n\n" if prev_summary else "")
            + "Give Steven a complete financial assessment:\n"
            "1. CASH POSITION: How much liquid cash does he have right now?\n"
            "2. DEBT OVERVIEW: Total debt, what's charged off vs active, what needs attention\n"
            "3. SPENDING ANALYSIS: Where is money going? What subscriptions or recurring charges should he cut?\n"
            "4. INCOME: What's coming in, how often, what's the monthly surplus/deficit?\n"
            "5. THIS WEEK: What's the single most important thing to do?\n"
            "6. 90-DAY PLAN: Prioritized debt payoff strategy with specific dollar amounts\n"
            "7. DATA GAPS: What info do you still need? Ask ONE specific question.\n"
        )

    result = await ctx.brain.query(
        prompt, system_prompt=ADVISOR_SYSTEM,
        tier=Tier.STANDARD, use_conversation=False,
    )

    # Save to memory
    await save_profile(ctx, 'last_advice_summary', result[:500])
    await save_profile(ctx, 'last_advice_date', datetime.date.today().isoformat())
    total_debt = sum(a['balance'] for a in profile['all_debts'])
    total_debt += sum(d['balance'] for d in profile['stored_debts'])
    await save_profile(ctx, 'last_known_debt_total', total_debt)

    try:
        await ctx.store.execute(
            "INSERT INTO finance_advisor_log (summary, recommendations) VALUES (?, ?)",
            (summary[:1000], result[:2000])
        )
    except Exception:
        pass

    return result


async def update_debt(ctx, institution: str, account_name: str,
                      balance: float, status: str = 'current',
                      minimum_payment: float = None, apr: float = None,
                      due_date: str = None, notes: str = None) -> None:
    now = datetime.datetime.now().isoformat()
    await ctx.store.execute(
        """INSERT INTO finance_debts
           (institution, account_name, account_type, balance, minimum_payment,
            apr, due_date, status, notes, updated_at)
           VALUES (?, ?, 'credit_card', ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(institution, account_name) DO UPDATE SET
           balance=excluded.balance, minimum_payment=excluded.minimum_payment,
           apr=excluded.apr, due_date=excluded.due_date, status=excluded.status,
           notes=excluded.notes, updated_at=excluded.updated_at""",
        (institution, account_name, balance, minimum_payment,
         apr, due_date, status, notes, now)
    )


async def handle_manual_update(ctx, text: str) -> str:
    """Handle natural language balance updates like 'I paid 2k on my mortgage'."""
    PARSE_SYSTEM = """Parse this financial update from the user. Return ONLY JSON:
{"action":"payment"|"balance_update","institution":"name or null","account":"name or null","amount":0.00,"notes":"brief summary"}
If you can't parse it: {"action":"unknown"}
Raw JSON only, no markdown."""

    result = await ctx.brain.query(
        text, system_prompt=PARSE_SYSTEM,
        tier=Tier.FAST, use_conversation=False,
    )

    try:
        import re
        result = re.sub(r',\s*([}\]])', r'\1', result.strip())
        start = result.find('{')
        end = result.rfind('}')
        if start == -1:
            return "I couldn't understand that update. Try: 'paid 500 on chase visa'"
        data = json.loads(result[start:end+1])

        if data.get('action') == 'unknown':
            return "I couldn't parse that. Try something like: 'paid 2000 on mortgage' or 'chase balance is now 1500'"

        institution = data.get('institution', 'Unknown')
        account = data.get('account', institution)
        amount = float(data.get('amount', 0))

        if data['action'] == 'payment':
            # Look up existing debt and reduce balance
            if await _table_exists(ctx.store, 'finance_debts'):
                debts = await ctx.store.fetchall(
                    "SELECT * FROM finance_debts WHERE LOWER(institution) LIKE ? OR LOWER(account_name) LIKE ?",
                    (f"%{institution.lower()}%", f"%{account.lower()}%")
                )
                if debts:
                    d = debts[0]
                    new_balance = max(0, d['balance'] - amount)
                    await update_debt(ctx, d['institution'], d['account_name'], new_balance,
                                    status=d['status'], notes=f"Payment of ${amount:,.2f} on {datetime.date.today()}")
                    return f"Recorded ${amount:,.2f} payment on {d['institution']} {d['account_name']}. New balance: ${new_balance:,.2f}"

            # No existing debt found — create one with the payment noted
            await update_debt(ctx, institution, account, 0, notes=f"Payment of ${amount:,.2f}")
            return f"Recorded ${amount:,.2f} payment on {institution} {account}."

        elif data['action'] == 'balance_update':
            await update_debt(ctx, institution, account, amount,
                            notes=f"Manual update {datetime.date.today()}")
            return f"Updated {institution} {account} balance to ${amount:,.2f}."

    except Exception as e:
        return f"Error processing update: {e}"
