"""Email that acts — Albus drafts, you approve, Gmail sends.

"reply to the school email saying we'll be there" → Albus finds the message,
drafts a reply in your voice (REASON tier), and sends it to Telegram with
Send/Discard buttons. Nothing leaves without a button press. Requires the
gmail.modify scope (re-run tools/google_auth.py after upgrading scopes).
"""
from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText

from pa.core.brain import Tier
from pa.plugins import AppContext

logger = logging.getLogger(__name__)

_DRAFT_SYSTEM = """You draft emails on behalf of the owner of a personal assistant. Write in a warm, plain, direct style — a busy dad, not a corporation. Short paragraphs, no fluff, sign off with the owner's first name. Return ONLY JSON:
{"to": "recipient email", "subject": "subject line", "body": "the email body"}
For replies keep the existing subject with Re: prefix. Never invent commitments the owner didn't state.
If this is about scheduling an appointment/meeting and calendar availability is provided, propose 2-3 SPECIFIC times that do not conflict with the busy list."""

_SCHEDULING_WORDS = (
    "schedule", "appointment", "book", "reschedule", "set up a time",
    "available", "availability", "meet", "meeting", "what times",
)


def _smells_like_scheduling(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in _SCHEDULING_WORDS)


async def _calendar_context(ctx: AppContext) -> str:
    """Busy times for the next 14 days, for conflict-free proposals."""
    try:
        from pa.plugins.google.calendar import upcoming_events
        from pa.plugins.google.client import calendar_service
        events = upcoming_events(calendar_service(ctx.vault), days=14)
    except Exception as e:
        if ctx.ledger is not None:
            await ctx.ledger.record(e, source="email_calendar_context")
        return ""
    if not events:
        return "\n\nOwner's calendar for the next 14 days: completely open."
    busy = "\n".join(
        f"  {e['start'][:16].replace('T', ' ')} — {e['summary']}" for e in events[:20]
    )
    return f"\n\nOwner's calendar (next 14 days, BUSY at these times):\n{busy}"


async def draft_email(ctx: AppContext, instruction: str) -> str:
    """NL entry: find context (if a reply), draft, stage for approval."""
    from pa.plugins.google.client import gmail_service
    from pa.plugins.google.gmail import search_emails

    if not ctx.vault.is_unlocked:
        return "Vault is locked — /unlock first so I can reach Gmail."

    owner = ctx.profile.owner if ctx.profile else "me"

    # If this is a reply, find the referenced email for context
    reply_context = ""
    original = None
    lower = instruction.lower()
    if "reply" in lower or "respond" in lower:
        try:
            terms = await ctx.brain.query_json(
                f'Extract 2-4 Gmail search words to find the email being '
                f'referred to: "{instruction}"\n'
                'Return {"query": "search words"}',
                tier=Tier.PARSE, max_tokens=100,
            )
            service = gmail_service(ctx.vault)
            hits = search_emails(
                service, terms.get("query", ""), max_results=3, fetch_body=True
            )
            if hits:
                original = hits[0]
                reply_context = (
                    f"\n\nEmail being replied to:\n"
                    f"From: {original.get('sender', '?')}\n"
                    f"Subject: {original.get('subject', '?')}\n"
                    f"Body:\n{(original.get('body') or '')[:1500]}"
                )
        except Exception as e:
            if ctx.ledger is not None:
                await ctx.ledger.record(e, source="email_draft_lookup")

    calendar_context = ""
    if _smells_like_scheduling(instruction):
        calendar_context = await _calendar_context(ctx)

    draft = await ctx.brain.query_json(
        f"The owner ({owner}) says: \"{instruction}\"{reply_context}"
        f"{calendar_context}\n\nDraft the email.",
        tier=Tier.REASON, system=_DRAFT_SYSTEM, max_tokens=800,
    )
    to_addr = (draft.get("to") or "").strip()
    if original and not to_addr:
        to_addr = original.get("sender", "")
    if not to_addr or "@" not in to_addr:
        return (
            "I drafted it but couldn't determine the recipient — "
            "tell me the address and I'll stage it."
        )

    outbox_id = await ctx.store.execute(
        "INSERT INTO google_outbox (to_addr, subject, body, thread_id, orig_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            to_addr,
            draft.get("subject", "(no subject)"),
            draft.get("body", ""),
            original.get("threadId") if original else None,
            original.get("message_id_header") if original else None,
        ),
    )
    await ctx.bot.send_approval(
        f"✉️ Draft #{outbox_id}\nTo: {to_addr}\n"
        f"Subject: {draft.get('subject', '')}\n\n{draft.get('body', '')}",
        approve_data=f"email:send:{outbox_id}",
        reject_data=f"email:discard:{outbox_id}",
        approve_label="📤 Send",
        reject_label="🗑 Discard",
    )
    return ""  # the approval message IS the response


async def handle_email_callback(ctx: AppContext, update, payload: str) -> str:
    action, _, outbox_id = payload.partition(":")
    if action not in ("send", "discard") or not outbox_id.isdigit():
        return "That email action made no sense to me."
    row = await ctx.store.fetchone(
        "SELECT * FROM google_outbox WHERE id = ?", (int(outbox_id),)
    )
    if row is None:
        return f"Draft #{outbox_id} no longer exists."
    if row["status"] != "staged":
        return f"Draft #{outbox_id} is already {row['status']}."

    if action == "discard":
        await ctx.store.execute(
            "UPDATE google_outbox SET status = 'discarded' WHERE id = ?",
            (row["id"],),
        )
        return f"🗑 Draft #{outbox_id} discarded."

    try:
        from pa.plugins.google.client import gmail_service
        service = gmail_service(ctx.vault)
        msg = MIMEText(row["body"])
        msg["To"] = row["to_addr"]
        msg["Subject"] = row["subject"]
        if row["orig_message_id"]:
            msg["In-Reply-To"] = row["orig_message_id"]
            msg["References"] = row["orig_message_id"]
        payload_body = {
            "raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()
        }
        if row["thread_id"]:
            payload_body["threadId"] = row["thread_id"]
        service.users().messages().send(userId="me", body=payload_body).execute()
        await ctx.store.execute(
            "UPDATE google_outbox SET status = 'sent' WHERE id = ?", (row["id"],)
        )
        return f"📤 Sent to {row['to_addr']}."
    except Exception as e:
        if ctx.ledger is not None:
            await ctx.ledger.record(e, source="email_send")
        hint = ""
        if "insufficient" in str(e).lower() or "scope" in str(e).lower():
            hint = (
                "\nGmail needs the upgraded permission — run "
                "tools/google_auth.py on the Pi once to re-authorize."
            )
        return f"⚠️ Send failed: {str(e)[:200]}{hint}"


async def handle_email_nl(ctx: AppContext, text: str, update) -> str:
    text = text.split("\n\n[Context from prior steps:")[0].strip()
    return await draft_email(ctx, text)


async def check_outbox_replies(ctx: AppContext, cal_service, emails: list[dict]) -> list[str]:
    """Surface replies to emails Albus sent; book confirmed appointments.

    Called from the Gmail check job with the already-fetched unread list.
    Returns the message ids it consumed (they skip normal triage)."""
    import datetime

    sent_threads = await ctx.store.fetchall(
        "SELECT thread_id, subject FROM google_outbox "
        "WHERE status = 'sent' AND thread_id IS NOT NULL "
        "AND created_at >= datetime('now', '-30 days')"
    )
    if not sent_threads:
        return []
    by_thread = {t["thread_id"]: t["subject"] for t in sent_threads}

    consumed: list[str] = []
    for email in emails:
        thread = email.get("threadId")
        if not thread or thread not in by_thread:
            continue
        consumed.append(email["id"])
        try:
            today = datetime.date.today().isoformat()
            extraction = await ctx.brain.query_json(
                f"Today is {today}. This is a reply to an email the owner sent "
                f"(subject: {by_thread[thread]}).\n"
                f"From: {email.get('sender')}\n"
                f"Content: {email.get('body') or email.get('snippet', '')}\n\n"
                "Does it confirm a specific appointment date+time? Return "
                '{"confirmed": true/false, "summary": "e.g. Dentist — Maddox", '
                '"date": "YYYY-MM-DD or null", "time": "HH:MM or null", '
                '"gist": "one sentence: what the reply says"}',
                tier=Tier.PARSE, max_tokens=200,
            )
        except Exception as e:
            if ctx.ledger is not None:
                await ctx.ledger.record(e, source="outbox_reply_parse")
            extraction = {}

        gist = extraction.get("gist") or email.get("snippet", "")[:150]
        note = f"📬 Reply on \"{by_thread[thread]}\" from {email.get('sender')}:\n{gist}"

        if extraction.get("confirmed") and extraction.get("date"):
            try:
                from pa.plugins.google.calendar import create_event
                create_event(cal_service, {
                    "title": extraction.get("summary") or by_thread[thread],
                    "date": extraction["date"],
                    "time": extraction.get("time"),
                })
                note += (
                    f"\n📅 Booked: {extraction.get('summary')} — "
                    f"{extraction['date']}"
                    + (f" {extraction['time']}" if extraction.get("time") else "")
                )
            except Exception as e:
                if ctx.ledger is not None:
                    await ctx.ledger.record(e, source="outbox_reply_calendar")
                note += "\n(Couldn't create the calendar event — recorded.)"

        await ctx.bot.send_message(note)
    return consumed
