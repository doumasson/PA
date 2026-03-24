"""Scheduled Gmail check job - unified email triage + bill extraction + learning."""
from __future__ import annotations
from datetime import datetime
from pa.plugins import Job


async def check_gmail(ctx) -> None:
    """Check Gmail - triage important emails AND extract financial data automatically."""
    if not ctx.vault.is_unlocked:
        return

    from pa.plugins.google.client import gmail_service, calendar_service
    from pa.plugins.google.gmail import get_unread_since
    from pa.plugins.google.triage import classify_emails_batch
    from pa.plugins.google.calendar import create_event
    from pa.plugins.finance.repository import FinanceRepository
    import json

    try:
        gmail = gmail_service(ctx.vault)
        cal = calendar_service(ctx.vault)
    except Exception as e:
        return

    emails = get_unread_since(gmail, max_results=50)
    if not emails:
        return

    # One batch Haiku call - classify AND extract financial data simultaneously
    COMBINED_SYSTEM = """You are an email assistant for Steve Hemenover, a busy dad with two sons Maddox (12) and Asher (10).

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
    repo = FinanceRepository(ctx.store)
    bills_updated = []

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

        # Handle bill data extraction - runs regardless of notify
        bill = r.get('bill')
        if bill and bill.get('balance') and float(bill.get('balance', 0)) > 0:
            try:
                institution = bill.get('institution', 'Unknown')
                account_name = bill.get('account_name', institution)
                balance = float(bill['balance'])
                minimum = bill.get('minimum_payment')
                due_date = bill.get('due_date')
                account_type = bill.get('account_type', 'credit_card')
                status = bill.get('status', 'current')

                existing = await repo.get_accounts()
                existing_map = {(a['institution'].lower(), a['name'].lower()): a['id'] for a in existing}
                key = (institution.lower(), account_name.lower())

                if key in existing_map:
                    account_id = existing_map[key]
                else:
                    account_id = await repo.add_account(
                        institution=institution,
                        name=account_name,
                        account_type=account_type,
                    )

                await repo.add_balance(
                    account_id=account_id,
                    balance=balance,
                    minimum_payment=float(minimum) if minimum else None,
                    due_date=due_date,
                )

                # Create calendar event for due date
                if due_date:
                    try:
                        min_str = f"${float(minimum):,.2f} min" if minimum else ""
                        create_event(cal, {
                            'title': f"💳 {institution} Payment Due {min_str}".strip(),
                            'date': due_date,
                            'duration_minutes': 30,
                        })
                    except Exception:
                        pass

                bills_updated.append(f"{institution}: ${balance:,.2f}")

            except Exception as e:
                print(f"Bill update error: {e}")

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
        print(f"Bills updated from email: {', '.join(bills_updated)}")


def get_google_jobs() -> list[Job]:
    return [
        Job(name="gmail_check_6am",  handler=check_gmail, trigger="cron", kwargs={"hour": 6,  "minute": 0}),
        Job(name="gmail_check_10am", handler=check_gmail, trigger="cron", kwargs={"hour": 10, "minute": 0}),
        Job(name="gmail_check_2pm",  handler=check_gmail, trigger="cron", kwargs={"hour": 14, "minute": 0}),
        Job(name="gmail_check_6pm",  handler=check_gmail, trigger="cron", kwargs={"hour": 18, "minute": 0}),
    ]
