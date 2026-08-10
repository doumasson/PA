"""Scheduled Gmail check job - unified email triage + bill extraction + learning."""
from __future__ import annotations
import logging
from datetime import datetime
from pa.plugins import Job

log = logging.getLogger(__name__)


def _to_float(val) -> float:
    """Parse a balance that may arrive as '1,234.56', '$1,234', or a number."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("$", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _event_exists(cal_service, cal_event: dict) -> bool:
    """True if an event with the same date and a similar title already exists,
    so re-scanned emails and confirmation+reminder pairs don't double-book."""
    from pa.plugins.google.calendar import upcoming_events
    date = (cal_event.get('date') or '')[:10]
    if not date:
        return False
    title = (cal_event.get('title') or '').strip().lower()
    try:
        for ev in upcoming_events(cal_service, days=400):
            if (ev.get('start') or '')[:10] != date:
                continue
            existing = (ev.get('summary') or '').strip().lower()
            if existing and title and (existing == title
                                       or existing in title or title in existing):
                return True
    except Exception:
        pass
    return False


async def _kid_sport_override(store, kid_name: str) -> str | None:
    """google_state override for a kid's sport (set via 'Maddox now plays soccer')."""
    try:
        row = await store.fetchone(
            "SELECT value FROM google_state WHERE key = ?",
            (f"kid_{kid_name.lower()}_sport",),
        )
        return row['value'] if row else None
    except Exception:
        return None


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
        if ctx.ledger:
            await ctx.ledger.record(e, source="google.check_gmail")
        return

    emails = get_unread_since(gmail, max_results=50)
    if not emails:
        return

    # TTL cleanup: purge notification records older than 14 days
    await _cleanup_old_notifications(ctx.store)

    # Dedup: skip emails we already notified about
    emails = await _filter_already_notified(ctx.store, emails)
    if not emails:
        return

    # Replies to emails Albus sent get surfaced immediately (and confirmed
    # appointments get booked); they skip normal triage.
    try:
        from pa.plugins.google.outbox import check_outbox_replies
        consumed = await check_outbox_replies(ctx, cal, emails)
        if consumed:
            await _record_notified_emails(ctx.store, consumed)
            emails = [e for e in emails if e["id"] not in set(consumed)]
        if not emails:
            return
    except Exception as e:
        if ctx.ledger:
            await ctx.ledger.record(e, source="google.outbox_replies")

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

    # Family facts come from the profile; google_state kid-sport overrides win.
    owner = ctx.profile.owner if ctx.profile else "the user"
    kids = list(ctx.profile.kids) if ctx.profile else []

    kid_bits = []
    sport_rules = []
    for kid in kids:
        sport = await _kid_sport_override(ctx.store, kid.name)
        age = kid.age()
        desc = kid.name + (f" ({age})" if age is not None else "")
        if sport:
            desc += f", plays {sport.upper()}"
        elif kid.notes:
            desc += f" — {kid.notes}"
        kid_bits.append(desc)
        if sport:
            sport_rules.append(f"- {kid.name} plays {sport.upper()}")
            sport_rules.append(f'- Calendar title format: "{kid.name} {sport.title()}"')
            sport_rules.append(f"- If an email mentions {sport.lower()}, it's about {kid.name.upper()}")

    kids_line = f" with kids: {'; '.join(kid_bits)}" if kid_bits else ""
    kid_names = " or ".join(k.name for k in kids) if kids else "the user's kids"
    sport_block = ""
    if sport_rules:
        sport_block = "\n\nKids sports — IMPORTANT:\n" + "\n".join(sport_rules)
    elif kids:
        sport_block = '\n\nKids sports calendar title format: "<Kid name> <Sport>"'

    # Load learned user preferences to inject into the triage prompt
    pref_block = ""
    if ctx.learning:
        try:
            prefs = await ctx.learning.all_of_kind("preference", limit=10)
        except Exception:
            prefs = []
        if prefs:
            pref_lines = "\n".join(
                f"- {p['value'].get('text', p['key'])}" for p in prefs
            )
            pref_block = f"\n\nUser preferences (MUST follow these):\n{pref_lines}\n"

    import datetime as _dt
    _today = _dt.date.today()
    # One batch Haiku call - classify AND extract financial data simultaneously
    COMBINED_SYSTEM = f"""You are an email assistant for {owner}, a busy parent{kids_line}.

Today is {_today.isoformat()} ({_today.strftime('%A')}). Resolve relative dates
("this Friday", "tomorrow", "next week") against today, and for any date with no
year use the nearest FUTURE date — never a past one.

Return ONLY a JSON object of the form {{"results": [...]}} with one entry per email:
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
- Golf programs, camps, tournaments (unless {owner} signed up)
- Rewards program updates, points notifications
- Food delivery promotions (Grubhub, DoorDash, etc.)
- Job alert emails from LinkedIn or job boards
- App store / subscription renewal receipts under $20

NOTIFY — only these:
- action+high = urgent response needed (real person expecting reply)
- event = anything with a specific date/time the owner must show up for or
  be aware of → notify=true, add calendar_event. This includes:
  APPOINTMENT CONFIRMATIONS (medical, dental, vet, school conferences,
  contractor/service visits, car service), sports practices/games,
  school events, reservations. Title format: "What — Provider"
  (e.g. "Dentist — Maddox — Comfort Dental"). An appointment
  confirmation/reminder email ALWAYS gets a calendar_event.
- ALWAYS flag: charge-off warnings, past due notices, fraud alerts, overdraft → notify=true, urgency=high
- School notices specifically about {kid_names} (not generic newsletters)
- Large purchases or transactions over $100{sport_block}

Bill extraction rules — BE AGGRESSIVE:
- Extract from ANY email resembling a statement, collection notice, past-due alert, payment confirmation, or balance notification
- Look for: "balance", "amount due", "minimum payment", "past due", "charged off", "collections", "amount owed", "statement", "payment due"
- institution = the company name (e.g. "CreditOne", "Mission Lane", "AdventHealth")
- account_name = specific card/account name if available, else same as institution
- account_type: credit_card for credit cards, loan for personal/auto loans, mortgage for home loans, utility for bills
- due_date in YYYY-MM-DD format; for a date with no year use the nearest future date (see today's date above)
- status: charged_off if email mentions charge-off/collections/written off, past_due if overdue/late, current otherwise
- minimum_payment: extract if available
- Set bill=null ONLY if there is absolutely no financial data in the email
{pref_block}
When in doubt: noise with notify=false.
Return ONLY the JSON object, no markdown."""

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
                    if _event_exists(cal, cal_event):
                        event_note = f" → 📅 already on calendar: {cal_event.get('title', 'event')}"
                    else:
                        event_id = create_event(cal, cal_event)
                        if event_id:
                            when = cal_event.get('date', '')
                            if cal_event.get('time'):
                                when += f" {cal_event['time']}"
                            event_note = f" → 📅 booked: {cal_event.get('title', 'event')} ({when})"
                except Exception as e:
                    if ctx.ledger:
                        await ctx.ledger.record(e, source="google.triage_calendar")
                    event_note = " (calendar booking failed — recorded)"

            icon = "🔴" if urgency == "high" else "📧"
            notifications.append(f"{icon} {summary}{event_note}")

        # Collect bill data for batch save - runs regardless of notify
        bill = r.get('bill')
        if bill and _to_float(bill.get('balance')) > 0:
            pending_bills.append(bill)

    # Save all extracted bills via the advisor's save_bills_to_db (handles
    # finance_accounts, finance_balances, AND finance_debts in one shot)
    bills_updated = []
    if pending_bills:
        try:
            saved = await save_bills_to_db(ctx, pending_bills)
            if saved:
                bills_updated = [
                    f"{b.get('institution', '?')}: ${_to_float(b.get('balance')):,.2f}"
                    for b in pending_bills
                ]
                log.info("Saved %d/%d bills from email", saved, len(pending_bills))
        except Exception as e:
            log.error("Bill save failed (non-fatal): %s", e, exc_info=True)
            if ctx.ledger:
                await ctx.ledger.record(e, source="google.check_gmail.bill_save")

    # Also save utility/insurance/subscription bills to the finance_bills table
    # (credit_card/loan/mortgage stay as debts only)
    _BILL_ACCOUNT_TYPES = {'utility', 'insurance', 'subscription'}
    if pending_bills:
        for bill in pending_bills:
            if bill.get('account_type') in _BILL_ACCOUNT_TYPES:
                try:
                    bill_name = bill.get('account_name') or bill.get('institution', 'Unknown')
                    category = bill.get('account_type', 'utility')
                    amount = _to_float(bill.get('balance')) or _to_float(bill.get('minimum_payment'))
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

    # Record notified email IDs FIRST so a later failure can't cause the same
    # emails to be re-triaged and re-booked on the next run.
    now = int(datetime.now().timestamp())
    await ctx.store.execute(
        "INSERT INTO google_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ('last_gmail_check', str(now))
    )
    notified_ids = [em['id'] for em in emails if classified.get(em['id'])]
    if notified_ids:
        await _record_notified_emails(ctx.store, notified_ids)

    # Create calendar events for bill due dates (separate from DB save so
    # a calendar failure doesn't block persistence). Deduped so repeated
    # scans don't stack identical "Payment Due" events.
    for bill in pending_bills:
        due_date = bill.get('due_date')
        if due_date:
            try:
                institution = bill.get('institution', 'Unknown')
                minimum = bill.get('minimum_payment')
                min_str = f"${_to_float(minimum):,.2f} min" if minimum else ""
                ev = {
                    'title': f"💳 {institution} Payment Due {min_str}".strip(),
                    'date': due_date,
                    'duration_minutes': 30,
                }
                if not _event_exists(cal, ev):
                    create_event(cal, ev)
            except Exception as e:
                if ctx.ledger:
                    await ctx.ledger.record(e, source="google.bill_calendar")

    # Send notifications
    if notifications:
        deduped = list(dict.fromkeys(notifications))
        await ctx.bot.send_message("**Emails worth your attention:**\n" + "\n".join(deduped))

    # Log bill updates silently (no message unless something new)
    if bills_updated:
        log.info("Bills updated from email: %s", ', '.join(bills_updated))


async def _filter_already_notified(store, emails: list[dict]) -> list[dict]:
    """Remove emails we've already notified about."""
    if not emails:
        return emails
    ids = [em['id'] for em in emails]
    placeholders = ','.join('?' for _ in ids)
    rows = await store.fetchall(
        f"SELECT message_id FROM google_notified_emails WHERE message_id IN ({placeholders})",
        tuple(ids),
    )
    seen = {r['message_id'] for r in rows}
    filtered = [em for em in emails if em['id'] not in seen]
    if len(filtered) < len(emails):
        log.info("Email dedup filtered %d/%d already-notified emails", len(emails) - len(filtered), len(emails))
    return filtered


async def _record_notified_emails(store, message_ids: list[str]) -> None:
    """Record email IDs we've notified about."""
    for mid in message_ids:
        await store.execute(
            "INSERT OR IGNORE INTO google_notified_emails (message_id) VALUES (?)",
            (mid,),
        )


async def _cleanup_old_notifications(store) -> None:
    """Delete notification records older than 14 days."""
    await store.execute(
        "DELETE FROM google_notified_emails WHERE notified_at < datetime('now', '-14 days')",
    )


def get_google_jobs() -> list[Job]:
    return [
        Job(name="gmail_check_morning", handler=check_gmail, trigger="cron", kwargs={"hour": 7, "minute": 0}),
    ]
