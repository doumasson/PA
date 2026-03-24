"""Email bill extractor - finds latest statement per institution."""
from __future__ import annotations
import datetime
import json
from pa.core.tier import Tier

# One broad query to get all bill-type emails
BILL_QUERY = '(subject:"statement" OR subject:"payment due" OR subject:"bill is ready" OR subject:"statement is available") after:{since}'

EXTRACT_SYSTEM = """Extract bill/statement data from these emails. Return ONLY a JSON array, no markdown.

For each email return:
{"id":"email_id","institution":"name","account_name":"card or account name","account_type":"credit_card|loan|mortgage|utility","balance":0.00,"minimum_payment":null,"due_date":"YYYY-MM-DD or null","found":true}

If no financial data: {"id":"email_id","found":false}

Rules:
- balance = amount owed/statement balance
- due_date in YYYY-MM-DD, assume 2026 if year missing
- Nelnet = student loan
- PayPal Credit = credit_card  
- Comcast = utility
- Return ONLY raw JSON array, nothing else"""


async def run_bill_extraction(ctx, days_back: int = 90, notify: bool = True) -> str:
    from pa.plugins.google.client import gmail_service, calendar_service
    from pa.plugins.finance.repository import FinanceRepository
    from pa.plugins.google.calendar import create_event

    gmail = gmail_service(ctx.vault)
    since = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime('%Y/%m/%d')
    query = BILL_QUERY.format(since=since)

    # Get all matching emails in one call
    seen_ids = set()
    emails = []
    page_token = None

    while len(emails) < 200:
        params = {'userId': 'me', 'q': query, 'maxResults': 100}
        if page_token:
            params['pageToken'] = page_token
        result = gmail.users().messages().list(**params).execute()
        for m in result.get('messages', []):
            if m['id'] not in seen_ids:
                seen_ids.add(m['id'])
                full = gmail.users().messages().get(
                    userId='me', id=m['id'], format='metadata',
                    metadataHeaders=['From', 'Subject']
                ).execute()
                headers = {h['name']: h['value'] for h in full['payload']['headers']}
                emails.append({
                    'id': m['id'],
                    'sender': headers.get('From', '')[:60],
                    'subject': headers.get('Subject', '')[:80],
                    'snippet': full.get('snippet', '')[:300],
                })
        page_token = result.get('nextPageToken')
        if not page_token:
            break

    if not emails:
        return "No bill emails found."

    # Deduplicate by sender — keep only most recent per sender
    by_sender = {}
    for e in emails:
        sender_key = e['sender'].split('<')[-1].split('>')[0].split('@')[-1]
        if sender_key not in by_sender:
            by_sender[sender_key] = e

    unique_emails = list(by_sender.values())
    print(f"Found {len(emails)} bill emails, deduped to {len(unique_emails)} unique senders")

    # One big Haiku call for all unique emails
    email_list = "\n\n".join(
        f"ID:{e['id']}\nFrom:{e['sender']}\nSubject:{e['subject']}\nContent:{e['snippet']}"
        for e in unique_emails
    )
    msg = f"Extract bill data from these {len(unique_emails)} emails:\n\n{email_list}"

    try:
        text = await ctx.brain.query(msg, system_prompt=EXTRACT_SYSTEM, tier=Tier.FAST)
        text = text.strip()
        if '```' in text:
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        start = text.find('[')
        end = text.rfind(']')
        if start == -1 or end == -1:
            return f"Could not parse response from {len(unique_emails)} emails."
        all_results = json.loads(text[start:end+1])
    except Exception as e:
        return f"Extraction failed: {e}"

    # Save to DB
    repo = FinanceRepository(ctx.store)
    cal = calendar_service(ctx.vault)
    saved = []
    calendar_events = []

    for r in all_results:
        if not r.get('found') or not r.get('balance'):
            continue
        institution = r.get('institution', 'Unknown')
        account_name = r.get('account_name', institution)
        balance = float(r.get('balance') or 0)
        minimum = r.get('minimum_payment')
        due_date = r.get('due_date')
        account_type = r.get('account_type', 'credit_card')

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
        saved.append(f"{institution} {account_name}: ${balance:,.2f}" + (f" due {due_date}" if due_date else ""))

        if due_date:
            try:
                min_str = f"${float(minimum):,.2f} min" if minimum else ""
                create_event(cal, {
                    'title': f"💳 {institution} Payment Due {min_str}",
                    'date': due_date,
                    'duration_minutes': 30,
                })
                calendar_events.append(f"{institution} due {due_date}")
            except Exception:
                pass

    if not saved:
        return f"Scanned {len(unique_emails)} unique senders, no balance data found."

    msg = f"Found {len(saved)} accounts:\n" + "\n".join(f"  • {s}" for s in saved)
    if calendar_events:
        msg += "\n\n📅 Calendar events:\n" + "\n".join(f"  {e}" for e in calendar_events)
    return msg
