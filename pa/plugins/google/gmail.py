"""Gmail fetcher - gets unread emails from today."""
from __future__ import annotations
from datetime import datetime, timezone


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
        emails.append({
            'id': msg['id'],
            'subject': headers.get('Subject', '(no subject)'),
            'sender': headers.get('From', 'unknown'),
            'date': headers.get('Date', ''),
            'snippet': full.get('snippet', '')[:300],
        })

    return emails
