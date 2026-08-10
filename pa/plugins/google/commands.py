"""Gmail plugin commands."""
from __future__ import annotations
import re
from telegram import Update
from telegram.ext import ContextTypes
from pa.plugins import AppContext
from pa.core.brain import Tier


async def _remember_preference(ctx: AppContext, text: str) -> None:
    """Persist a stated preference in the unified learning store."""
    if ctx.learning:
        await ctx.learning.remember(
            "preference", text[:200], {"text": text[:200]}, source="google"
        )


async def handle_email_block(ctx: AppContext, text: str, update: Update) -> str:
    """Handle requests to block email senders/topics. Zero API calls."""
    tl = text.lower()

    # Extract what they don't want
    # Patterns: "stop sending me X emails", "I don't care about X", "block X emails"
    patterns = [
        r"(?:stop|quit|don't|dont)\s+(?:sending|showing|telling)\s+(?:me\s+)?(?:about\s+)?(.+?)(?:\s+emails?)?$",
        r"(?:i\s+)?(?:don't|dont)\s+care\s+about\s+(.+?)(?:\s+emails?)?$",
        r"block\s+(.+?)(?:\s+emails?)?$",
        r"(?:i'm\s+)?not\s+interested\s+in\s+(.+?)(?:\s+emails?)?$",
        r"(?:mute|ignore|filter out|hide)\s+(.+?)(?:\s+emails?)?$",
    ]

    topic = None
    for pat in patterns:
        m = re.search(pat, tl)
        if m:
            topic = m.group(1).strip().rstrip('.')
            break

    if not topic:
        # Fallback: grab the key noun after complaint keywords
        for kw in ["about ", "from "]:
            idx = tl.find(kw)
            if idx != -1:
                topic = tl[idx + len(kw):].strip().rstrip('.')
                break

    if not topic or len(topic) < 2:
        return "What emails should I stop showing you? Try: 'stop sending me LinkedIn emails' or 'I don't care about First Tee'"

    # Determine if it's a sender or topic keyword
    block_type = "sender" if any(x in topic for x in ["@", ".com", ".org", ".net"]) else "keyword"

    await ctx.store.execute(
        "INSERT OR IGNORE INTO google_email_blocks (block_type, pattern, reason) VALUES (?, ?, ?)",
        (block_type, topic.lower(), text.strip()[:200]),
    )

    # Also save as preference for the triage prompt
    await _remember_preference(ctx, f"Do NOT notify about {topic} emails")

    return f"Got it — I'll filter out {topic} emails from now on. Use /email_blocks to see what's blocked."


async def handle_email_blocks(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Show blocked email senders/topics."""
    rows = await ctx.store.fetchall(
        "SELECT block_type, pattern, created_at FROM google_email_blocks ORDER BY created_at DESC"
    )
    if not rows:
        return "No email blocks set. Tell me 'stop sending me X emails' to add one."
    lines = ["**Blocked Email Topics/Senders**\n"]
    for r in rows:
        lines.append(f"  [{r['block_type']}] {r['pattern']}")
    lines.append("\nUse /email_unblock <pattern> to remove one.")
    return "\n".join(lines)


async def handle_email_unblock(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Remove an email block."""
    args = context.args or []
    if not args:
        return "Usage: /email_unblock <pattern>"
    pattern = " ".join(args).lower()
    rows = await ctx.store.execute_rowcount(
        "DELETE FROM google_email_blocks WHERE LOWER(pattern) = ?", (pattern,)
    )
    if rows == 0:
        return f"No block found for '{pattern}'. Use /email_blocks to see all."
    return f"Unblocked: {pattern}"


async def handle_kid_sport(ctx: AppContext, text: str, update: Update) -> str:
    """Update what sport a kid plays. Stored in google_state, used by email triage.

    Handles corrections like:
    - "Asher is the soccer player, not Maddox"
    - "Maddox plays basketball, Asher plays soccer"
    - "Asher is soccer, Maddox is basketball"
    """
    tl = text.lower()

    sports = ["basketball", "football", "soccer", "baseball", "hockey", "lacrosse",
              "swimming", "tennis", "golf", "volleyball", "wrestling", "track",
              "cross country", "gymnastics"]

    kids = list(ctx.profile.kids) if ctx.profile else []
    mentioned = [k.name.lower() for k in kids if k.name.lower() in tl]

    found_sports = [s for s in sports if s in tl]

    updates = []

    if len(mentioned) >= 2 and found_sports:
        # Multiple kids mentioned — use the LLM to parse the correction
        kid_desc = ", ".join(
            k.name + (f" ({k.age()})" if k.age() is not None else "") for k in kids
        )
        try:
            data = await ctx.brain.query_json(
                text,
                tier=Tier.PARSE,
                system=(
                    f'Extract kid-sport assignments from this message. Kids are {kid_desc}. '
                    'Return JSON: {"assignments": [{"kid": "<name>", "sport": "<sport>"}, ...]}'
                ),
            )
            for p in data.get('assignments') or []:
                if p.get('kid') and p.get('sport'):
                    updates.append((p['kid'].lower(), p['sport'].lower()))
        except Exception:
            pass

    if not updates:
        # Single kid or fallback — original logic
        kid = mentioned[0] if mentioned else None

        sport = None
        for s in sports:
            if s in tl:
                sport = s
                break

        if not kid:
            example = kids[0].name.capitalize() if kids else "Alex"
            return f"Which kid? Try: '{example} is now playing football'"
        if not sport:
            return f"What sport? Try: '{kid.capitalize()} is now playing football'"
        updates.append((kid, sport))

    confirmations = []
    for kid, sport in updates:
        await ctx.store.execute(
            "INSERT INTO google_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"kid_{kid}_sport", sport),
        )
        await _remember_preference(
            ctx, f"{kid.capitalize()} plays {sport.upper()} (not other sports)"
        )
        confirmations.append(f"{kid.capitalize()} plays {sport}")

    return f"Got it — {', '.join(confirmations)}. I'll update the email triage."


async def handle_gmail_check(ctx: AppContext, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Manually trigger a Gmail check."""
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    await update.message.reply_text("Checking Gmail...")

    from pa.plugins.google.jobs import check_gmail
    await check_gmail(ctx)
    return "Done. I'll message you if anything needs attention."


async def handle_gmail_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Handle natural language Gmail/calendar queries."""
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    tl = text.lower()

    if any(w in tl for w in ["check", "any emails", "any email", "emails", "what's in", "inbox", "new email", "unread", "critical", "important", "urgent"]):
        await update.message.reply_text("Checking Gmail...")
        from pa.plugins.google.jobs import check_gmail
        try:
            await check_gmail(ctx)
            return "Done — I'll message you if anything needs attention."
        except Exception as e:
            if ctx.ledger:
                await ctx.ledger.record(e, source="google.gmail_nl")
            return f"Gmail error: {e}"

    # For calendar queries
    if any(w in tl for w in ["calendar", "schedule", "appointment"]):
        return await handle_calendar_nl(ctx, text, update)

    # Default: check gmail
    await update.message.reply_text("Checking Gmail...")
    from pa.plugins.google.jobs import check_gmail
    try:
        await check_gmail(ctx)
        return "Done — I'll message you if anything needs attention."
    except Exception as e:
        if ctx.ledger:
            await ctx.ledger.record(e, source="google.gmail_nl")
        return f"Gmail error: {e}"


async def handle_calendar_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Real calendar handling: list upcoming events, or delete one by name.

    Deleted events land in Google Calendar's trash, so a wrong delete is
    recoverable — but we still only act on a single unambiguous match.
    """
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    from pa.plugins.google.client import calendar_service
    from pa.plugins.google.calendar import upcoming_events, find_events, delete_event

    tl = text.lower()
    destructive = any(
        w in tl for w in ["kill", "delete", "remove", "get rid of", "cancel the"]
    )

    try:
        service = calendar_service(ctx.vault)
    except Exception as e:
        if ctx.ledger:
            await ctx.ledger.record(e, source="google.calendar_nl")
        return f"Calendar error: {e}"

    if destructive:
        system = (
            "The user wants to delete a calendar event. Extract the event "
            "name they're referring to.\n"
            'Return ONLY raw JSON: {"event": "<name or empty string>"}'
        )
        query = ""
        try:
            data = await ctx.brain.query_json(text, tier=Tier.PARSE, system=system)
            query = str(data.get("event") or "").strip()
        except ValueError:
            pass
        if not query:
            return "Which calendar event should I delete?"
        try:
            matches = find_events(service, query)
        except Exception as e:
            if ctx.ledger:
                await ctx.ledger.record(e, source="google.calendar_nl")
            return f"Calendar error: {e}"
        if not matches:
            return f"No calendar events match '{query}'."
        summaries = {m["summary"] for m in matches}
        if len(summaries) > 1:
            listing = "\n".join(
                f"  - {m['summary']} ({m['start'][:10]})" for m in matches[:10]
            )
            return f"A few different events match '{query}' — which one?\n{listing}"
        deleted = []
        for m in matches:
            try:
                delete_event(service, m["id"])
            except Exception as e:
                if ctx.ledger:
                    await ctx.ledger.record(e, source="google.calendar_nl")
                return f"Couldn't delete '{m['summary']}': {e}"
            kind = "recurring series" if m["recurring"] else "event"
            deleted.append(f"Deleted {kind}: {m['summary']}")
        return "\n".join(deleted) + "\n(Recoverable from Calendar trash for 30 days.)"

    try:
        events = upcoming_events(service, days=14)
    except Exception as e:
        if ctx.ledger:
            await ctx.ledger.record(e, source="google.calendar_nl")
        return f"Calendar error: {e}"
    if not events:
        return "Nothing on the calendar for the next two weeks."
    lines = ["Next two weeks:"]
    for ev in events:
        lines.append(f"  {ev['start'][:16].replace('T', ' ')} — {ev['summary']}")
    return "\n".join(lines)


async def handle_email_search(ctx: AppContext, text: str, update: Update) -> str:
    """Search for specific emails and extract data (balances, due dates, etc.)."""
    if not ctx.vault.is_unlocked:
        return "Vault is locked. Send /unlock first."

    # Check if we already have this data in the debts DB
    tl = text.lower()
    debts = await ctx.store.fetchall(
        "SELECT institution, account_name, balance, minimum_payment, due_date, updated_at "
        "FROM finance_debts ORDER BY updated_at DESC"
    )
    if debts:
        # See if any stored debt matches what the user is asking about
        for d in debts:
            inst = d['institution'].lower()
            if inst in tl or any(w in tl for w in inst.split()):
                # Data exists and is less than 24 hours old
                import datetime
                try:
                    updated = datetime.datetime.fromisoformat(d['updated_at'])
                    age = datetime.datetime.now() - updated
                    if age.total_seconds() < 86400:
                        line = f"**{d['institution']}** {d['account_name']}: ${d['balance']:,.2f}"
                        if d.get('minimum_payment'):
                            line += f" (min payment: ${d['minimum_payment']:,.2f})"
                        if d.get('due_date'):
                            line += f" due {d['due_date']}"
                        return line
                except Exception:
                    pass

    # Use Claude to parse what the user is looking for
    PARSE = """Parse this email search request. Return ONLY JSON:
{"sender": "company name or null", "subject": "subject keywords or null", "action": "search"|"extract_balance"|"extract_and_save", "days_back": 7}
Rules for action:
- "extract_and_save": user wants to find a balance/statement AND save/track it as a debt (default for credit cards, bills, loans)
- "extract_balance": user asks "how much do I owe" or wants to know a balance from email
- "search": user just wants to find/read emails, no financial extraction
If in doubt between search and extract, choose "extract_balance" — it's better to extract and show than to just summarize."""

    try:
        data = await ctx.brain.query_json(text, tier=Tier.PARSE, system=PARSE)
    except Exception:
        data = {"sender": None, "subject": None, "action": "search", "days_back": 7}

    # Build Gmail search query
    parts = []
    if data.get("sender"):
        parts.append(f"from:{data['sender']}")
    if data.get("subject"):
        parts.append(f"subject:{data['subject']}")
    days = data.get("days_back", 7)
    if days and days <= 30:
        from datetime import datetime, timedelta
        after = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        parts.append(f"after:{after}")

    query = " ".join(parts) if parts else "is:unread"

    await update.message.reply_text(f"Searching emails: {query}...")

    from pa.plugins.google.client import gmail_service
    from pa.plugins.google.gmail import search_emails
    try:
        gmail = gmail_service(ctx.vault)
        emails = search_emails(gmail, query, max_results=5, fetch_body=True)
    except Exception as e:
        if ctx.ledger:
            await ctx.ledger.record(e, source="google.email_search")
        return f"Gmail error: {e}"

    if not emails:
        return f"No emails found matching: {query}"

    # Build summary for Claude to analyze
    email_summaries = []
    for e in emails:
        summary = f"From: {e['sender']}\nSubject: {e['subject']}\nDate: {e['date']}\n"
        if e['body']:
            summary += f"Body excerpt: {e['body'][:1000]}\n"
        else:
            summary += f"Snippet: {e['snippet']}\n"
        email_summaries.append(summary)

    all_emails = "\n---\n".join(email_summaries)

    # Always extract and save financial data from emails
    EXTRACT = """From the emails below, extract financial data. Return ONLY JSON of the form:
{"accounts": [{"institution": "company name", "account_name": "card/account name", "account_type": "credit_card"|"store_card"|"charge_card"|"loan"|"mortgage"|"medical"|"utility",
 "balance": 0.00, "minimum_payment": 0.00, "due_date": "YYYY-MM-DD or null"}]}
Include one entry per account found; use an empty list if none."""

    try:
        extract_data = await ctx.brain.query_json(
            f"User asked: {text}\n\nEmails:\n{all_emails}",
            tier=Tier.PARSE, system=EXTRACT, max_tokens=2048,
        )
        extracted = extract_data.get("accounts") or []
        if isinstance(extracted, dict):
            extracted = [extracted]
    except Exception:
        return f"Found {len(emails)} emails but couldn't extract balance data. Here's what I found:\n\n{emails[0]['snippet']}"

    # Always save extracted data to debts
    from pa.plugins.finance.advisor import update_debt

    results = []
    for item in extracted:
        if item.get("balance") is not None:
            await update_debt(
                ctx,
                institution=item.get("institution", "Unknown"),
                account_name=item.get("account_name", "Account"),
                balance=float(item["balance"]),
                minimum_payment=float(item["minimum_payment"]) if item.get("minimum_payment") else None,
                due_date=item.get("due_date"),
                account_type=item.get("account_type", "credit_card"),
            )
            line = (
                f"**{item.get('institution')}** {item.get('account_name')}: "
                f"${float(item['balance']):,.2f}"
                + (f" (min payment: ${float(item['minimum_payment']):,.2f})" if item.get('minimum_payment') else "")
                + (f" due {item['due_date']}" if item.get('due_date') else "")
            )
            results.append(line)

    if results:
        return "Extracted and saved:\n" + "\n".join(results)

    # Fallback: summarize if no financial data found
    SUMMARIZE = f"User asked: '{text}'\n\nFound {len(emails)} emails:\n{all_emails}\n\nSummarize what's relevant. Be concise."
    return await ctx.brain.complete(SUMMARIZE, tier=Tier.PARSE, context_id=None)
