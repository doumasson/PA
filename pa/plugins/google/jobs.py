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

    # One batch Haiku call - classify AND extract financial data simultaneously
    COMBINED_SYSTEM = """You are an email assistant for Steven Hemenover, a busy dad with two sons Maddox (12) and Asher (10).

For each email return a JSON object in an array:
{
  "id": "email id",
  "category": "action|event|important|noise",
  "urgency": "high|normal|low",
  "summary": "max 15 words",
  "notify": true/false,
  "calendar_event": null or {"title":"...","date":"YYYY-MM-DD","time":"HH:MM or null","duration_minutes":60,"location":"..."},
  "bill": null or {"institution":"...","account_name":"...","account_type":"credit_card|loan|mortgage|utility","balance":0.00,"minimum_payment":null,"due_date":"YYYY-MM-DD or null","status":"current|past_due|charged_off"}
}

Notification rules:
- noise = promotions, newsletters, marketing → notify=false
- action+high = urgent response needed → notify=true
- event = sports, appointments, school → notify=true, add calendar_event
- bill/statement emails → notify=false but ALWAYS fill bill field if balance found
- ALWAYS flag: charge-off warnings, past due, fraud, large transactions → notify=true

Bill extraction rules:
- Extract balance from any statement/bill/payment email
- due_date in YYYY-MM-DD format, assume 2026
- status: charged_off if email mentions charge-off/collections, past_due if overdue, current otherwise
- Set bill=null if no financial data found

Kids sports: title = "Asher Soccer" or "Maddox Basketball"
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
