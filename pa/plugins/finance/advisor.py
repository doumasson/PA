"""Autonomous Financial Advisor Agent — persistent memory, Gmail integration, spending analysis."""
from __future__ import annotations
import datetime
import json
import logging
import re
from pa.core.brain import Tier

log = logging.getLogger(__name__)

ADVISOR_SYSTEM_TEMPLATE = """You are Bart, {owner}'s personal financial advisor.
You have direct access to his real financial data — bank accounts, credit cards, transactions, and bills from email.

Your voice: you speak as Albus Dumbledore would — warm, wise, measured, with the
occasional touch of gentle wit. Never "straight talk, no fluff" bravado, never
corporate bullet-speak in the prose. But Dumbledore's kindness never blunts his
candor: name hard truths plainly, use exact numbers and dates, and say precisely
what to do and in what order. Judgment-free, always on {owner}'s side.

{owner}'s situation:
- SOME accounts are intentionally in default as part of a deliberate legal strategy he manages. ONLY the accounts the data marks charged_off (or that the OWNER STRATEGY note lists) are charged off — never assume an account is charged off because others are
- His mortgage handling is likewise deliberate — protect essentials, don't nag
- His income figures are NET take-home (already after taxes and deductions) — never re-deduct taxes from them
- He needs to know: what he owes, what's due, where he's overspending, what subscriptions to cut

Never say "consult a financial advisor" — YOU are his financial advisor.

RESPONSE RULES:
- Answer the question asked. Do NOT upsell other commands or suggest /advisor.
- Factual queries (balances, debts, spending totals) get UNDER 80 WORDS. Numbers first, commentary second.
- No rhetorical questions. No "shall we explore this further?" or "would you like me to..."
- Save advisory tone for explicit advice requests or /advisor sessions.
- Never add disclaimers about consulting professionals.
- Format debt/balance lists as tight tables, not paragraphs.

For charged-off accounts: explain options (settlement, pay-for-delete, ignore if past SOL).
For active debt: prioritize by urgency (due dates, interest rates).
For spending: flag subscriptions, recurring charges, and areas to cut.
For income: estimate from deposits, calculate surplus/deficit, recommend allocation.

If data is missing, say exactly what you need. Ask ONE specific question to fill the biggest gap."""


def _owner(ctx) -> str:
    return ctx.profile.owner if ctx.profile else "the user"


def _inst_key(institution: str) -> str:
    """First word of the institution, so 'Citi' matches 'Citibank'."""
    word = (institution or "").lower().split()[0] if (institution or "").split() else ""
    return word[:4] if len(word) > 4 else word


def _card_last4(name: str) -> str | None:
    digits = re.findall(r"\d{4,}", name or "")
    return digits[-1][-4:] if digits else None


def _same_account(inst_a: str, name_a: str, inst_b: str, name_b: str) -> bool:
    """Fuzzy account identity. Gmail bill extraction names the same card a
    little differently every scan ('Cash Back Visa ending 4009' vs 'Mission
    Lane Cash Back Visa'), which used to spawn duplicate accounts and debts.
    Same institution + same last-4 (or no last-4 on either side) = same account."""
    if _inst_key(inst_a) != _inst_key(inst_b):
        return False
    a4, b4 = _card_last4(name_a), _card_last4(name_b)
    if a4 and b4:
        return a4 == b4
    # No last-4 to compare: distinct product names at the same institution
    # (CreditOne 'American Express' vs 'Visa') must stay separate.
    generic = {"card", "credit", "account", "ending", "in", "the", "consumer", "rewards"}
    inst_words = set((inst_a or "").lower().split()) | set((inst_b or "").lower().split())

    def _toks(name: str) -> set[str]:
        return set(re.sub(r"[^a-z ]", " ", (name or "").lower()).split()) - generic - inst_words

    ta, tb = _toks(name_a), _toks(name_b)
    if ta and tb and not (ta & tb):
        return False
    return True


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

        EXTRACT_SYSTEM = """Extract bill/debt data from these emails. Return ONLY a JSON object: {"bills": [...]}.
For each email, add one entry to "bills": {"id":"x","institution":"name","account_name":"name","account_type":"credit_card|loan|mortgage|utility","balance":0.00,"minimum_payment":null,"due_date":"YYYY-MM-DD or null","apr":null,"status":"current|past_due|charged_off","found":true}
If the email mentions past due, late, charged off, or collections — set status accordingly.
If no financial data: {"id":"x","found":false}
Assume the current or nearest-future year for dates without one. Return raw JSON only, no markdown."""

        email_list = "\n\n".join(
            f"ID:{e['id']}\nFrom:{e['sender']}\nSubject:{e['subject']}\nContent:{e['snippet']}"
            for e in emails
        )
        data = await ctx.brain.query_json(
            f"Extract bill data from {len(emails)} emails:\n\n{email_list}",
            tier=Tier.PARSE, system=EXTRACT_SYSTEM, max_tokens=4096,
        )
        results = data.get('bills', [])
        return [r for r in results if r.get('found') and (r.get('balance') or r.get('due_date'))]
    except Exception as e:
        if getattr(ctx, "ledger", None) is not None:
            await ctx.ledger.record(e, source="gmail_bill_scan")
        else:
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
            match = next(
                (a for a in existing
                 if _same_account(a['institution'], a['name'], institution, account_name)),
                None,
            )
            if match:
                account_id = match['id']
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
                # Reuse the existing debt row's exact names — the UNIQUE
                # (institution, account_name) upsert would otherwise spawn a
                # duplicate debt every time an email words the name differently.
                debt_rows = await ctx.store.fetchall(
                    "SELECT institution, account_name, balance FROM finance_debts"
                )
                existing_debt = next(
                    (d for d in debt_rows
                     if _same_account(d['institution'], d['account_name'], institution, account_name)),
                    None,
                )
                if existing_debt:
                    if abs(float(existing_debt['balance']) - balance) > 0.01:
                        log.info("Debt balance changed: %s %s: $%,.2f → $%,.2f",
                                 institution, account_name, float(existing_debt['balance']), balance)
                    institution = existing_debt['institution']
                    account_name = existing_debt['account_name']

                await update_debt(
                    ctx, institution, account_name, balance,
                    status=bill.get('status', 'current'),
                    minimum_payment=float(bill['minimum_payment']) if bill.get('minimum_payment') else None,
                    apr=float(bill['apr']) if bill.get('apr') else None,
                    due_date=bill.get('due_date'),
                )

            saved += 1
        except Exception as e:
            log.error("Bill save error: %s", e)
    return saved


async def get_financial_profile(ctx, include_gmail: bool = False) -> dict:
    """Build complete financial profile from all sources."""
    from pa.plugins.finance.repository import FinanceRepository
    repo = FinanceRepository(ctx.store)

    memory = await load_profile(ctx)

    balances = await repo.get_latest_balances()
    since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    txns = await repo.get_transactions(since_date=since, limit=200)

    # Categorize transactions using the learning system
    from pa.plugins.finance.merchants import categorize_transactions
    txns = await categorize_transactions(ctx.store, txns)

    # Income = deposits (negative amounts = money coming in), but cash-advance
    # disbursements (Brigit/Cleo/Dave/Earnin) are LOANS, not income — excluding
    # them keeps the estimate and the surplus/deficit honest.
    _ADVANCE_MARKERS = ("brigit", "cleo", "dave", "earnin", "instant pmt from")
    credits = [
        t for t in txns
        if t['amount'] < 0
        and not any(m in (t['description'] or '').lower() for m in _ADVANCE_MARKERS)
    ]
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

    # Self-teaching: save estimates and track month-over-month
    if income_estimate > 0:
        await save_profile(ctx, 'income_estimate', income_estimate)
    if spending_estimate > 0:
        await save_profile(ctx, 'spending_estimate', spending_estimate)
        # Track monthly spending history for trend detection
        history = memory.get('spending_history', [])
        today = datetime.date.today().isoformat()
        # Only add if we haven't already logged today
        if not history or history[-1].get('date') != today:
            history.append({'date': today, 'amount': spending_estimate})
            history = history[-12:]  # Keep last 12 data points
            await save_profile(ctx, 'spending_history', history)

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


def _debts_not_already_stored(all_debts: list, stored: list) -> list:
    """Teller/Gmail debt balances that aren't a duplicate of a manually
    tracked debt, deduped among themselves as well (the same medical bill
    can surface as two differently named accounts)."""
    extra: list = []
    for a in all_debts:
        if a['balance'] <= 0:
            continue
        if any(_same_account(d['institution'], d['account_name'], a['institution'], a['name'])
               for d in stored):
            continue
        if any(_same_account(e['institution'], e['name'], a['institution'], a['name'])
               for e in extra):
            continue
        extra.append(a)
    return extra


async def build_financial_summary(profile: dict) -> str:
    lines = [f"Financial snapshot as of {profile['as_of']}:\n"]

    # Owner-stated strategy overrides conventional advice — always first.
    strategy = profile.get('memory', {}).get('debt_strategy_context')
    if strategy:
        lines.append(f"⚑ OWNER STRATEGY (respect this in ALL advice):\n{strategy}\n")

    # Standing facts the owner has stated — corrections to what the raw
    # data alone would suggest.
    notes = profile.get('memory', {}).get('owner_notes') or []
    if notes:
        lines.append("OWNER NOTES (owner-stated facts, trust over inference):")
        for n in notes:
            lines.append(f"  - {n}")
        lines.append("")

    if profile['checking_accounts']:
        lines.append("LIQUID ASSETS:")
        total_liquid = 0
        for a in profile['checking_accounts']:
            lines.append(f"  {a['institution']} {a['name']}: ${a['balance']:,.2f}")
            total_liquid += a['balance']
        lines.append(f"  TOTAL LIQUID: ${total_liquid:,.2f}")

    # One deduped debt list. Manual rows are authoritative; Teller/Gmail
    # balances only add accounts not already tracked manually — listing both
    # sources used to make the model double-count the same card.
    stored = profile['stored_debts']
    extra = _debts_not_already_stored(profile['all_debts'], stored)
    if stored or extra:
        total = sum(d['balance'] for d in stored) + sum(a['balance'] for a in extra)
        lines.append(f"\nDEBTS — complete deduped list (total ${total:,.2f}):")
        for d in sorted(stored, key=lambda x: x['balance'], reverse=True):
            line = f"  {d['institution']} {d['account_name']}: ${d['balance']:,.2f} [{d['status']}]"
            if d.get('apr'):
                line += f" @ {d['apr']:.1f}% APR"
            if d.get('due_date'):
                line += f" due {d['due_date']}"
            if d.get('notes'):
                line += f" — {d['notes']}"
            lines.append(line)
        for a in sorted(extra, key=lambda x: x['balance'], reverse=True):
            line = f"  {a['institution']} {a['name']} ({a['type']}): ${a['balance']:,.2f}"
            if a.get('interest_rate'):
                line += f" @ {a['interest_rate']:.1f}% APR"
            if a.get('minimum_payment'):
                line += f" min ${a['minimum_payment']:,.2f}"
            if a.get('due_date'):
                line += f" due {a['due_date']}"
            lines.append(line)

    # Income
    monthly = profile.get('monthly_income', 0)
    estimated = profile.get('income_estimate', 0)
    if monthly > 0:
        lines.append(f"\nMONTHLY TAKE-HOME INCOME (NET, after taxes and deductions): ${monthly:,.2f}")
    elif estimated > 0:
        lines.append(f"\nESTIMATED NET INCOME (last 30d deposits): ${estimated:,.2f}")

    spending = profile.get('spending_estimate', 0)
    if spending > 0:
        lines.append(f"SPENDING (last 30 days): ${spending:,.2f}")
        income_val = monthly or estimated
        if income_val > 0:
            surplus = income_val - spending
            lines.append(f"SURPLUS/DEFICIT: ${surplus:,.2f}")

    # Spending breakdown by LEARNED category
    if profile['recent_transactions']:
        debits = [t for t in profile['recent_transactions'] if t['amount'] > 0]
        if debits:
            # Group by learned category
            by_cat = {}
            uncategorized = []
            for t in debits:
                cat = t.get('learned_category')
                if cat:
                    by_cat.setdefault(cat, []).append(t)
                else:
                    uncategorized.append(t)

            if by_cat:
                lines.append("\nSPENDING BY CATEGORY (last 30 days):")
                for cat in sorted(by_cat.keys(), key=lambda c: sum(t['amount'] for t in by_cat[c]), reverse=True):
                    total_cat = sum(t['amount'] for t in by_cat[cat])
                    lines.append(f"  {cat}: ${total_cat:,.2f} ({len(by_cat[cat])} transactions)")
                    for t in by_cat[cat][:3]:
                        lines.append(f"    {t['date']} {t['description'][:35]}: ${t['amount']:,.2f}")

            if uncategorized:
                lines.append(f"\n  UNCATEGORIZED ({len(uncategorized)} transactions):")
                for t in uncategorized[:10]:
                    lines.append(f"    {t['date']} {t['description'][:35]}: ${t['amount']:,.2f}")

    # Spending trend (self-teaching: tracks month over month)
    memory = profile.get('memory', {})
    spending_history = memory.get('spending_history', [])
    if len(spending_history) >= 2:
        lines.append("\nSPENDING TREND:")
        for entry in spending_history[-6:]:
            lines.append(f"  {entry['date']}: ${entry['amount']:,.2f}")
        prev = spending_history[-2]['amount']
        curr = spending_history[-1]['amount']
        if prev > 0:
            change_pct = ((curr - prev) / prev) * 100
            direction = "UP" if change_pct > 0 else "DOWN"
            lines.append(f"  Change: {direction} {abs(change_pct):.1f}%")

    # Spending concerns from recurring detection
    concerns = memory.get('spending_concerns', [])
    if concerns:
        lines.append("\nSPENDING CONCERNS (auto-detected):")
        for c in concerns:
            lines.append(f"  - {c}")

    # Recurring payments from memory
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
    owner = _owner(ctx)

    if user_question:
        prompt = (
            f"{summary}\n\n"
            + (f"Previous analysis: {prev_summary}\n\n" if prev_summary else "")
            + f"{owner}'s question: {user_question}\n\n"
            "Answer specifically using his real numbers. "
            "If he's asking about spending, identify specific merchants and amounts. "
            "If he's asking about debt, show totals and suggest priority order. "
            "If he mentions a payment he made, acknowledge it."
        )
    else:
        prompt = (
            f"{summary}\n\n"
            + (f"Previous analysis: {prev_summary}\n\n" if prev_summary else "")
            + f"Give {owner} a complete financial assessment:\n"
            "1. CASH POSITION: How much liquid cash does he have right now?\n"
            "2. DEBT OVERVIEW: Total debt, what's charged off vs active, what needs attention\n"
            "3. SPENDING ANALYSIS: Where is money going? What subscriptions or recurring charges should he cut?\n"
            "4. INCOME: What's coming in, how often, what's the monthly surplus/deficit?\n"
            "5. THIS WEEK: What's the single most important thing to do?\n"
            "6. 90-DAY PLAN: Prioritized debt payoff strategy with specific dollar amounts\n"
            "7. DATA GAPS: What info do you still need? Ask ONE specific question.\n"
        )

    # Heavy analysis via CLIProxyAPI subscription — free, no cost concern
    result = await ctx.brain.complete(
        prompt, tier=Tier.REASON,
        system=ADVISOR_SYSTEM_TEMPLATE.format(owner=owner), context_id=None,
        max_tokens=4096,
    )

    # Save to memory
    await save_profile(ctx, 'last_advice_summary', result[:500])
    await save_profile(ctx, 'last_advice_date', datetime.date.today().isoformat())
    stored = profile['stored_debts']
    total_debt = sum(d['balance'] for d in stored)
    total_debt += sum(a['balance'] for a in _debts_not_already_stored(profile['all_debts'], stored))
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
                      due_date: str = None, notes: str = None,
                      account_type: str = 'credit_card') -> None:
    now = datetime.datetime.now().isoformat()
    await ctx.store.execute(
        """INSERT INTO finance_debts
           (institution, account_name, account_type, balance, minimum_payment,
            apr, due_date, status, notes, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(institution, account_name) DO UPDATE SET
           balance=excluded.balance, minimum_payment=excluded.minimum_payment,
           apr=excluded.apr, due_date=excluded.due_date, status=excluded.status,
           notes=excluded.notes, updated_at=excluded.updated_at""",
        (institution, account_name, account_type, balance, minimum_payment,
         apr, due_date, status, notes, now)
    )


async def handle_manual_update(ctx, text: str) -> str:
    """Handle natural language balance updates like 'I paid 2k on my mortgage'."""
    PARSE_SYSTEM = """Parse this financial update from the user. Return ONLY JSON:
{"action":"payment"|"balance_update","institution":"name or null","account":"name or null","amount":0.00,"notes":"brief summary"}
If you can't parse it: {"action":"unknown"}
Raw JSON only, no markdown."""

    try:
        data = await ctx.brain.query_json(text, tier=Tier.PARSE, system=PARSE_SYSTEM)

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
