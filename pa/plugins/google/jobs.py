"""Scheduled Gmail check job - unified email triage + bill extraction + learning."""
from __future__ import annotations
import logging
from datetime import datetime
from pa.plugins import Job

log = logging.getLogger(__name__)


async def check_gmail(ctx) -> None:
    """Check Gmail - triage important emails AND extract financial data automatically."""
    if not ctx.vault.is_unlocked:
        return

    from pa.plugins.google.client import gmail_service, calendar_service
    from pa.plugins.google.gmail import get_unread_since
    from pa.plugins.google.triage import classify_emails_batch
    from pa.plugins.google.calendar import create_event
    from pa.plugins.finance.advisor import save_bills_to_db

    try:
        gmail = gmail_service(ctx.vault)
        cal = calendar_service(ctx.vault)
    except Exception as e:
        return

    emails = get_unread_since(gmail, max_results=50)
    if not emails:
        return

    # Pre-filter: drop emails matching blocklist BEFORE sending to Haiku (zero API cost)
    try:
        blocks = await ctx.store.fetchall("SELECT block_type, pattern FROM google_email_blocks")
    except Exception:
        blocks = []
    if blocks:
        filtered = []
        for em in emails:
            sender_lower = em['sender'].lower()
            subject_lower = em['subject'].lower()
            snippet_lower = em.get('snippet', '').lower()
            blocked = False
            for b in blocks:
                pat = b['pattern'].lower()
                if b['block_type'] == 'sender' and pat in sender_lower:
                    blocked = True
                elif b['block_type'] == 'keyword' and (pat in subject_lower or pat in sender_lower or pat in snippet_lower):
                    blocked = True
                elif b['block_type'] == 'subject' and pat in subject_lower:
                    blocked = True
            if not blocked:
                filtered.append(em)
        if len(filtered) < len(emails):
            log.info("Email blocklist filtered %d/%d emails", len(emails) - len(filtered), len(emails))
        emails = filtered
        if not emails:
            return

    # Load kid sports dynamically from DB
    maddox_sport = "BASKETBALL"
    asher_sport = "SOCCER"
    try:
        row = await ctx.store.fetchone("SELECT value FROM google_state WHERE key = 'kid_maddox_sport'")
        if row:
            maddox_sport = row['value'].upper()
        row = await ctx.store.fetchone("SELECT value FROM google_state WHERE key = 'kid_asher_sport'")
        if row:
            asher_sport = row['value'].upper()
    except Exception:
        pass

    # Load user preferences to inject into triage prompt
    prefs = ctx.brain._preferences[-10:] if ctx.brain._preferences else []
    pref_block = ""
    if prefs:
        pref_lines = "\n".join(f"- {p}" for p in prefs)
        pref_block = f"\n\nUser preferences (MUST follow these):\n{pref_lines}\n"

    # One batch Haiku call - classify AND extract financial data simultaneously
    COMBINED_SYSTEM = f"""You are an email assistant for Steven Hemenover, a busy dad with two sons: Maddox (12, plays {maddox_sport}) and Asher (10, plays {asher_sport}).

For each email return a JSON object in an array:
{{
  "id": "email id",
  "category": "action|event|important|noise",
  "urgency": "high|normal|low",
  "summary": "max 15 words",
  "notify": true/false,
  "calendar_event": null or {{"title":"...","date":"YYYY-MM-DD","time":"HH:MM or null","duration_minutes":60,"location":"..."}},
  "bill": null or {{"institution":"...","account_name":"...","account_type":"credit_card|loan|mortgage|utility","balance":0.00,"minimum_payment":null,"due_date":"YYYY-MM-DD or null","status":"current|past_due|charged_off"}}
}}

NOISE — always notify=false:
- Promotions, deals, coupons, marketing, sales emails
- Newsletters, blog digests, content roundups
- Social media notifications
- Screen time requests/reports from kids' devices
- Automated shipping/tracking updates (unless explicitly high-value)
- Golf programs, camps, tournaments (unless Steven signed up)
- Rewards program updates, points notifications
- Food delivery promotions (Grubhub, DoorDash, etc.)
- Job alert emails from LinkedIn or job boards
- App store / subscription renewal receipts under $20

NOTIFY — only these:
- action+high = urgent response needed (real person expecting reply)
- event = sports PRACTICES or GAMES with specific date/time → notify=true, add calendar_event
- ALWAYS flag: charge-off warnings, past due notices, fraud alerts, overdraft → notify=true, urgency=high
- School notices specifically about Maddox or Asher (not generic newsletters)
- Large purchases or transactions over $100

Kids sports — IMPORTANT:
- Maddox plays {maddox_sport}
- Asher plays {asher_sport}
- Calendar title format: "Maddox {maddox_sport.title()}" or "Asher {asher_sport.title()}"
- If an email mentions {asher_sport.lower()}, it's about ASHER
- If an email mentions {maddox_sport.lower()}, it's about MADDOX

Bill extraction rules:
- Extract balance from any statement/bill/payment email
- due_date in YYYY-MM-DD format, assume 2026
- status: charged_off if email mentions charge-off/collections, past_due if overdue
- Set bill=null if no financial data found
{pref_block}
When in doubt: noise with notify=false.
Speak results only as JSON array, no markdown."""

    results = await classify_emails_batch(emails, ctx.brain, system_override=COMBINED_SYSTEM)
    if not results:
        return

    classified = {r['id']: r for r in results if isinstance(r, dict) and 'id' in r}

    notifications = []
    pending_bills = []

    for em in emails:
        r = classified.get(em['id'])
        if not r:
            continue

        # Handle notifications
        if r.get('notify'):
            category = r.get('category', 'noise')
            summary = r.get('summary', em['subject'])
            urgency = r.get('urgency', 'normal')
            cal_event = r.get('calendar_event')

            event_note = ""
            if cal_event and category == 'event':
                try:
                    event_id = create_event(cal, cal_event)
                    if event_id:
                        event_note = " 📅"
                except Exception:
                    pass

            icon = "🔴" if urgency == "high" else "📧"
            notifications.append(f"{icon} {summary}{event_note}")

        # Collect bill data for batch save - runs regardless of notify
        bill = r.get('bill')
        if bill and bill.get('balance') and float(bill.get('balance', 0)) > 0:
            pending_bills.append(bill)

    # Save all extracted bills via the advisor's save_bills_to_db (handles
    # finance_accounts, finance_balances, AND finance_debts in one shot)
    bills_updated = []
    if pending_bills:
        try:
            saved = await save_bills_to_db(ctx, pending_bills)
            if saved:
                bills_updated = [
                    f"{b.get('institution', '?')}: ${float(b['balance']):,.2f}"
                    for b in pending_bills
                ]
                log.info("Saved %d/%d bills from email", saved, len(pending_bills))
        except Exception as e:
            log.error("Bill save failed (non-fatal): %s", e, exc_info=True)

    # Also save utility/insurance/subscription bills to the finance_bills table
    # (credit_card/loan/mortgage stay as debts only)
    _BILL_ACCOUNT_TYPES = {'utility', 'insurance', 'subscription'}
    if pending_bills:
        for bill in pending_bills:
            if bill.get('account_type') in _BILL_ACCOUNT_TYPES:
                try:
                    bill_name = bill.get('account_name') or bill.get('institution', 'Unknown')
                    category = bill.get('account_type', 'utility')
                    amount = float(bill.get('balance') or bill.get('minimum_payment') or 0)
                    due_date = bill.get('due_date')
                    await ctx.store.execute(
                        "INSERT INTO finance_bills (name, category, amount, due_date, source) "
                        "VALUES (?, ?, ?, ?, 'email') "
                        "ON CONFLICT(name) DO UPDATE SET amount=excluded.amount, "
                        "due_date=excluded.due_date, updated_at=CURRENT_TIMESTAMP",
                        (bill_name, category, amount if amount > 0 else None, due_date),
                    )
                except Exception as e:
                    log.error("finance_bills save failed for %s: %s", bill.get('institution'), e)

    # Create calendar events for bill due dates (separate from DB save so
    # a calendar failure doesn't block persistence)
    for bill in pending_bills:
        due_date = bill.get('due_date')
        if due_date:
            try:
                institution = bill.get('institution', 'Unknown')
                minimum = bill.get('minimum_payment')
                min_str = f"${float(minimum):,.2f} min" if minimum else ""
                create_event(cal, {
                    'title': f"💳 {institution} Payment Due {min_str}".strip(),
                    'date': due_date,
                    'duration_minutes': 30,
                })
            except Exception:
                pass

    # Save timestamp
    now = int(datetime.now().timestamp())
    await ctx.store.execute(
        "INSERT INTO google_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ('last_gmail_check', str(now))
    )

    # Send notifications
    if notifications:
        deduped = list(dict.fromkeys(notifications))
        await ctx.bot.send_message("**Emails worth your attention:**\n" + "\n".join(deduped))

    # Log bill updates silently (no message unless something new)
    if bills_updated:
        log.info("Bills updated from email: %s", ', '.join(bills_updated))


def get_google_jobs() -> list[Job]:
    return [
        Job(name="gmail_check_6am",  handler=check_gmail, trigger="cron", kwargs={"hour": 6,  "minute": 0}),
        Job(name="gmail_check_10am", handler=check_gmail, trigger="cron", kwargs={"hour": 10, "minute": 0}),
        Job(name="gmail_check_2pm",  handler=check_gmail, trigger="cron", kwargs={"hour": 14, "minute": 0}),
        Job(name="gmail_check_6pm",  handler=check_gmail, trigger="cron", kwargs={"hour": 18, "minute": 0}),
    ]
