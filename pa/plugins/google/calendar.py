"""Google Calendar event creator."""
from __future__ import annotations
import datetime


def create_event(service, event_data: dict, calendar_id: str = 'primary') -> str | None:
    """Create a calendar event. Returns event ID or None on failure."""
    date_str = event_data.get('date')
    if not date_str:
        return None

    time_str = event_data.get('time')
    duration = event_data.get('duration_minutes', 60)

    if time_str:
        start_dt = datetime.datetime.fromisoformat(f"{date_str}T{time_str}:00")
        end_dt = start_dt + datetime.timedelta(minutes=duration)
        start = {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Denver'}
        end   = {'dateTime': end_dt.isoformat(),   'timeZone': 'America/Denver'}
    else:
        start = {'date': date_str}
        end   = {'date': date_str}

    body = {
        'summary': event_data.get('title', 'Event'),
        'location': event_data.get('location', ''),
        'start': start,
        'end': end,
    }

    event = service.events().insert(calendarId=calendar_id, body=body).execute()
    return event.get('id')
