"""Autonomous Financial Advisor Agent - with persistent memory and Gmail integration."""
from __future__ import annotations
import asyncio
import datetime
import json
from pa.core.tier import Tier

ADVISOR_SYSTEM = """You are an autonomous financial advisor AI for Steve Hemenover.
You have direct access to his real financial data — bank accounts, credit cards, transactions, and bills from email.

Steve's situation:
- He has intentionally defaulted on several credit cards
- He is in financial trouble and actively trying to dig out
- He does NOT want generic advice — he wants specific next steps based on his actual numbers
- He has a mortgage (Planet Home Lending) that is the priority to protect
- He has student loans (Nelnet)
- Several cards are charged off or in collections
- This is a judgment-free zone — be honest and practical

Your personality: Speak like Albus Dumbledore — wise, warm, direct, never condescending.
Never say "consult a financial advisor" — YOU are the financial advisor.
Be specific with numbers. Tell him exactly what to do and in what order.
If something is charged off, explain what that means practically and what his options are (settlement, pay-for-delete, ignore if past SOL).
Never sugarcoat. Steve can handle the truth.
If data is missing, say so clearly and ask ONE specific question to fill the most important gap."""


async def _table_exists(store, table_name: str) -> bool:
    row = await store.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return row is not None


async def save_profile(ctx, key: str, value) -> None:
    """Save a value to the persistent financial profile."""
    await ctx.store.execute(
        """INSERT INTO finance_profile (key, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (key, json.dumps(value), datetime.datetime.now().isoformat())
    )


async def load_profile(ctx) -> dict:
    """Load the persistent financial profile."""
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
        query = f'(subject:"statement" OR subject:"payment due" OR subject:"bill is ready" OR subject:"statement is available") after:{since}'

        result = gmail.users().messages().list(userId='me', q=query, maxResults=50).execute()
        messages = result.get('messages', [])
        if not messages:
            return []

        # Get snippets for all messages
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

        # One batch Haiku call to extract all bill data
        EXTRACT_SYSTEM = """Extract bill data from emails. Return ONLY a JSON array, no markdown.
For each email: {"id":"x","institution":"name","account_name":"name","account_type":"credit_card|loan|mortgage|utility","balance":0.00,"minimum_payment":null,"due_date":"YYYY-MM-DD or null","status":"current|past_due|charged_off","found":true}
If no financial data: {"id":"x","found":false}
Assume year 2026 for dates. Return raw JSON array only."""

        email_list = "\n\n".join(
            f"ID:{e['id']}\nFrom:{e['sender']}\nSubject:{e['subject']}\nContent:{e['snippet']}"
            for e in emails
        )
        text = await ctx.brain.query(
            f"Extract bill data from {len(emails)} emails:\n\n{email_list}",
            system_prompt=EXTRACT_SYSTEM,
            tier=Tier.FAST
        )
        text = text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        start = text.find('[')
        end = text.rfind(']')
        if start == -1:
            return []
        results = json.loads(text[start:end+1])
        return [r for r in results if r.get('found') and r.get('balance')]
    except Exception as e:
        print(f"Gmail bill scan error: {e}")
        return []


async def get_financial_profile(ctx) -> dict:
    """Build complete financial profile from all sources."""
    from pa.plugins.finance.repository import FinanceRepository
    repo = FinanceRepository(ctx.store)

    # Load persistent memory
    memory = await load_profile(ctx)

    # Get Teller data
    balances = await repo.get_latest_balances()  # already deduped by account_id
    since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=200)

    # Estimate income from deposits
    credits = [t for t in txns if t['amount'] < 0]
    income_estimate = abs(sum(t['amount'] for t in credits))

    # Estimate spending
    debits = [t for t in txns if t['amount'] > 0]
    spending_estimate = sum(t['amount'] for t in debits)

    # Categorize
    checking = [b for b in balances if b['type'] in ('checking', 'savings', 'depository')]
    teller_debts = [b for b in balances if b['type'] in ('credit_card', 'credit', 'loan', 'mortgage')]

    # Get manually added debts
    stored_debts = []
    if await _table_exists(ctx.store, 'finance_debts'):
        stored_debts = await ctx.store.fetchall("SELECT * FROM finance_debts ORDER BY balance DESC")

    # Scan Gmail for bills (only if explicitly requested)
    gmail_bills = []  # Called separately in weekly job

    # Save income estimate to memory
    if income_estimate > 0:
        await save_profile(ctx, 'income_estimate', income_estimate)
        await save_profile(ctx, 'income_updated', datetime.date.today().isoformat())

    # Save Gmail bills to DB
    if gmail_bills:
        for bill in gmail_bills:
            try:
                institution = bill.get('institution', 'Unknown')
                account_name = bill.get('account_name', institution)
                balance = float(bill.get('balance') or 0)
                if balance <= 0:
                    continue
                existing = await repo.get_accounts()
                existing_map = {(a['institution'].lower(), a['name'].lower()): a['id'] for a in existing}
                key = (institution.lower(), account_name.lower())
                if key in existing_map:
                    account_id = existing_map[key]
                else:
                    account_id = await repo.add_account(
                        institution=institution,
                        name=account_name,
                        account_type=bill.get('account_type', 'credit_card'),
                    )
                await repo.add_balance(
                    account_id=account_id,
                    balance=balance,
                    minimum_payment=float(bill['minimum_payment']) if bill.get('minimum_payment') else None,
                    due_date=bill.get('due_date'),
                )
            except Exception as e:
                print(f"Bill save error: {e}")

    # Reload balances after Gmail update
    balances = await repo.get_latest_balances()
    all_debts = [b for b in balances if b['type'] in ('credit_card', 'credit', 'loan', 'mortgage')]

    return {
        'checking_accounts': [b for b in balances if b['type'] in ('checking', 'savings', 'depository')],
        'all_debts': all_debts,
        'stored_debts': stored_debts,
        'income_estimate': income_estimate or memory.get('income_estimate', 0),
        'spending_estimate': spending_estimate,
        'recent_transactions': txns[:20],
        'gmail_bills_found': len(gmail_bills),
        'memory': memory,
        'as_of': datetime.date.today().isoformat(),
    }


async def build_financial_summary(profile: dict) -> str:
    lines = [f"Financial snapshot as of {profile['as_of']}:\n"]

    if profile['checking_accounts']:
        lines.append("LIQUID ASSETS:")
        for a in profile['checking_accounts']:
            lines.append(f"  {a['institution']} {a['name']}: ${a['balance']:,.2f}")

    if profile['all_debts']:
        total = sum(a['balance'] for a in profile['all_debts'])
        lines.append(f"\nKNOWN DEBTS (total ${total:,.2f}):")
        for a in profile['all_debts']:
            line = f"  {a['institution']} {a['name']} ({a['type']}): ${a['balance']:,.2f}"
            if a.get('minimum_payment'):
                line += f" min ${a['minimum_payment']:,.2f}"
            if a.get('due_date'):
                line += f" due {a['due_date']}"
            lines.append(line)

    if profile['stored_debts']:
        lines.append("\nMANUALLY TRACKED DEBTS:")
        for d in profile['stored_debts']:
            lines.append(f"  {d['institution']} {d['account_name']}: ${d['balance']:,.2f} [{d['status']}]")

    income = profile.get('income_estimate', 0)
    spending = profile.get('spending_estimate', 0)
    if income > 0:
        lines.append(f"\nESTIMATED MONTHLY INCOME: ${income:,.2f}")
    if spending > 0:
        lines.append(f"ESTIMATED MONTHLY SPENDING: ${spending:,.2f}")
        if income > 0:
            lines.append(f"ESTIMATED MONTHLY SURPLUS/DEFICIT: ${income - spending:,.2f}")

    if profile['recent_transactions']:
        lines.append("\nRECENT TRANSACTIONS (sample):")
        for t in profile['recent_transactions'][:10]:
            lines.append(f"  {t['date']} {t['description'][:40]}: ${t['amount']:,.2f}")

    if profile['gmail_bills_found'] > 0:
        lines.append(f"\nGmail scan found {profile['gmail_bills_found']} bill emails (data merged above)")

    # What we know we're missing
    lines.append("\nDATA GAPS:")
    lines.append("  - Planet Home Lending mortgage (not in Teller or Gmail yet)")
    lines.append("  - Exact APRs on charged-off accounts")
    lines.append("  - Whether any accounts are past statute of limitations")

    return "\n".join(lines)


async def run_advisor(ctx, user_question: str = None) -> str:
    """Run the full financial advisor."""
    profile = await get_financial_profile(ctx)
    summary = await build_financial_summary(profile)

    # Load previous advice for context
    memory = profile.get('memory', {})
    prev_summary = memory.get('last_advice_summary', '')

    if user_question:
        prompt = (
            f"{summary}\n\n"
            + (f"Previous analysis: {prev_summary}\n\n" if prev_summary else "")
            + f"Steve's question: {user_question}\n\n"
            f"Answer specifically using his real numbers. "
            f"Acknowledge what data is missing. "
            f"Ask ONE question if needed."
        )
    else:
        # Check if we're missing critical data
        missing = []
        if not memory.get('mortgage_payment'):
            missing.append("mortgage monthly payment amount")
        if not memory.get('monthly_income'):
            missing.append("monthly take-home income")

        prompt = (
            f"{summary}\n\n"
            + (f"Previous analysis: {prev_summary}\n\n" if prev_summary else "")
            + "Give Steve a complete financial assessment:\n"
            f"1. Where he stands right now (exact numbers)\n"
            f"2. What's most urgent THIS WEEK\n"
            f"3. 90-day action plan\n"
            f"4. What you'd do with any extra money\n"
            + (f"IMPORTANT: You are missing these critical data points: {', '.join(missing)}. Ask for the MOST important one at the end.\n" if missing else "")
        )

    result = await ctx.brain.query(prompt, system_prompt=ADVISOR_SYSTEM, tier=Tier.STANDARD)

    # Save to memory
    await save_profile(ctx, 'last_advice_summary', result[:500])
    await save_profile(ctx, 'last_advice_date', datetime.date.today().isoformat())
    await save_profile(ctx, 'last_known_debt_total',
        sum(a['balance'] for a in profile['all_debts']))

    # Log the run
    try:
        await ctx.store.execute(
            "INSERT INTO finance_advisor_log (summary, recommendations) VALUES (?, ?)",
            (summary[:1000], result[:1000])
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
