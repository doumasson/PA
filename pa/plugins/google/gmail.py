"""Gmail fetcher - gets unread emails from today."""
from __future__ import annotations
import base64
import re
from datetime import datetime, timezone


# Senders / subject keywords that indicate a bill or statement
_BILL_SENDERS = re.compile(
    r'(chase|wellsfargo|wells\s*fargo|citi|capital\s*one|discover|amex|'
    r'american\s*express|barclays|synchrony|navient|nelnet|mohela|'
    r'sofi|paypal|apple\s*card|bank\s*of\s*america|usaa|ally|'
    r'xfinity|comcast|verizon|t-?mobile|at&t|spectrum|cox|'
    r'progressive|geico|state\s*farm|allstate)',
    re.IGNORECASE,
)
_BILL_SUBJECTS = re.compile(
    r'(statement|bill|payment\s*due|amount\s*due|minimum\s*due|'
    r'balance|past\s*due|autopay|account\s*summary|pay\s*your)',
    re.IGNORECASE,
)


def _looks_like_bill(sender: str, subject: str) -> bool:
    return bool(_BILL_SENDERS.search(sender) and _BILL_SUBJECTS.search(subject))


def _extract_text_from_payload(payload: dict) -> str:
    """Recursively extract plain-text body from Gmail message payload."""
    parts = payload.get('parts', [])
    if parts:
        for part in parts:
            text = _extract_text_from_payload(part)
            if text:
                return text
    mime = payload.get('mimeType', '')
    if mime == 'text/plain':
        data = payload.get('body', {}).get('data', '')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
    # Fall back to text/html stripped of tags
    if mime == 'text/html':
        data = payload.get('body', {}).get('data', '')
        if data:
            html = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
            return re.sub(r'<[^>]+>', ' ', html)
    return ''


def get_unread_since(service, since_timestamp: int | None = None, max_results: int = 20) -> list[dict]:
    """Fetch unread emails from today only."""
    query = "is:unread"

    result = service.users().messages().list(
        userId='me', q=query, maxResults=max_results
    ).execute()

    messages = result.get('messages', [])
    emails = []
    for msg in messages:
        full = service.users().messages().get(
            userId='me', id=msg['id'], format='metadata',
            metadataHeaders=['From', 'Subject', 'Date']
        ).execute()

        headers = {h['name']: h['value'] for h in full['payload']['headers']}
        subject = headers.get('Subject', '(no subject)')
        sender = headers.get('From', 'unknown')
        snippet = full.get('snippet', '')[:300]

        # For bill/statement emails, fetch the full body so we get actual dollar amounts
        body = ''
        if _looks_like_bill(sender, subject):
            try:
                full_msg = service.users().messages().get(
                    userId='me', id=msg['id'], format='full'
                ).execute()
                body = _extract_text_from_payload(full_msg['payload'])[:3000]
            except Exception:
                pass

        emails.append({
            'id': msg['id'],
            'subject': subject,
            'sender': sender,
            'date': headers.get('Date', ''),
            'snippet': snippet,
            'body': body,
        })

    return emails
