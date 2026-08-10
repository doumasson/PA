"""Google Calendar event creator."""
from __future__ import annotations
import datetime


def create_event(service, event_data: dict, calendar_id: str = 'primary',
                 timezone: str = 'America/Denver') -> str | None:
    """Create a calendar event. Returns event ID or None on failure."""
    date_str = event_data.get('date')
    if not date_str:
        return None

    time_str = event_data.get('time')
    duration = event_data.get('duration_minutes', 60)

    if time_str:
        start_dt = datetime.datetime.fromisoformat(f"{date_str}T{time_str}:00")
        end_dt = start_dt + datetime.timedelta(minutes=duration)
        start = {'dateTime': start_dt.isoformat(), 'timeZone': timezone}
        end   = {'dateTime': end_dt.isoformat(),   'timeZone': timezone}
    else:
        # All-day events: Google treats end.date as EXCLUSIVE, so a one-day
        # event must end the following day or it renders as zero-length.
        start_date = datetime.date.fromisoformat(date_str)
        start = {'date': date_str}
        end   = {'date': (start_date + datetime.timedelta(days=1)).isoformat()}

    body = {
        'summary': event_data.get('title', 'Event'),
        'location': event_data.get('location', ''),
        'start': start,
        'end': end,
    }

    event = service.events().insert(calendarId=calendar_id, body=body).execute()
    return event.get('id')


def find_events(service, query: str, calendar_id: str = 'primary') -> list[dict]:
    """Events whose text matches query: [{id, summary, recurring, start}].

    singleEvents=False returns recurring MASTERS, so deleting an id here
    removes the whole series — which is what "kill that recurring event" means.
    """
    result = service.events().list(
        calendarId=calendar_id, q=query, maxResults=25, singleEvents=False,
    ).execute()
    events = []
    for e in result.get('items', []):
        if e.get('status') == 'cancelled':
            continue
        start = e.get('start', {})
        events.append({
            'id': e['id'],
            'summary': e.get('summary', '(untitled)'),
            'recurring': bool(e.get('recurrence')),
            'start': start.get('dateTime', start.get('date', '')),
        })
    return events


def delete_event(service, event_id: str, calendar_id: str = 'primary') -> None:
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()


def upcoming_events(service, days: int = 7, calendar_id: str = 'primary') -> list[dict]:
    """Events in the next N days: [{start, summary}] sorted by start."""
    import datetime
    now = datetime.datetime.utcnow()
    time_min = now.isoformat() + 'Z'
    time_max = (now + datetime.timedelta(days=days)).isoformat() + 'Z'
    result = service.events().list(
        calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
        singleEvents=True, orderBy='startTime', maxResults=25,
    ).execute()
    events = []
    for e in result.get('items', []):
        start = e.get('start', {})
        events.append({
            'start': start.get('dateTime', start.get('date', '')),
            'summary': e.get('summary', '(untitled)'),
        })
    return events
