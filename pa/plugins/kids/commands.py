"""Commands for the kids activity tracker plugin."""
from __future__ import annotations

import datetime
from typing import Any

from pa.plugins import AppContext


async def handle_kids(ctx: AppContext, update: Any, context: Any) -> str:
    """Show upcoming events for both kids this week."""
    today = datetime.date.today()
    week_end = today + datetime.timedelta(days=7)
    rows = await ctx.store.fetchall(
        "SELECT * FROM kids_events WHERE date >= ? AND date <= ? ORDER BY date, time",
        (today.isoformat(), week_end.isoformat()),
    )
    if not rows:
        return "No events scheduled for the boys this week."

    lines = ["This week's events:"]
    for r in rows:
        kid = r["kid"].capitalize()
        time_str = f" at {r['time']}" if r["time"] else ""
        loc = f" — {r['location']}" if r["location"] else ""
        lines.append(f"• {r['date']} {kid}: {r['title']}{time_str}{loc}")
    return "\n".join(lines)


async def handle_maddox(ctx: AppContext, update: Any, context: Any) -> str:
    """Maddox's upcoming events and recent notes."""
    today = datetime.date.today().isoformat()
    events = await ctx.store.fetchall(
        "SELECT * FROM kids_events WHERE kid = 'maddox' AND date >= ? ORDER BY date, time LIMIT 10",
        (today,),
    )
    notes = await ctx.store.fetchall(
        "SELECT * FROM kids_notes WHERE kid = 'maddox' ORDER BY created_at DESC LIMIT 5",
    )

    lines = ["Maddox (12, basketball)"]
    if events:
        lines.append("\nUpcoming events:")
        for e in events:
            time_str = f" at {e['time']}" if e["time"] else ""
            loc = f" — {e['location']}" if e["location"] else ""
            lines.append(f"• {e['date']}: {e['title']}{time_str}{loc}")
    else:
        lines.append("\nNo upcoming events.")

    if notes:
        lines.append("\nRecent notes:")
        for n in notes:
            lines.append(f"• {n['note']} ({n['category']})")

    return "\n".join(lines)


async def handle_asher(ctx: AppContext, update: Any, context: Any) -> str:
    """Asher's upcoming events and recent notes."""
    today = datetime.date.today().isoformat()
    events = await ctx.store.fetchall(
        "SELECT * FROM kids_events WHERE kid = 'asher' AND date >= ? ORDER BY date, time LIMIT 10",
        (today,),
    )
    notes = await ctx.store.fetchall(
        "SELECT * FROM kids_notes WHERE kid = 'asher' ORDER BY created_at DESC LIMIT 5",
    )

    lines = ["Asher (10, soccer)"]
    if events:
        lines.append("\nUpcoming events:")
        for e in events:
            time_str = f" at {e['time']}" if e["time"] else ""
            loc = f" — {e['location']}" if e["location"] else ""
            lines.append(f"• {e['date']}: {e['title']}{time_str}{loc}")
    else:
        lines.append("\nNo upcoming events.")

    if notes:
        lines.append("\nRecent notes:")
        for n in notes:
            lines.append(f"• {n['note']} ({n['category']})")

    return "\n".join(lines)


async def handle_kid_add(ctx: AppContext, update: Any, context: Any) -> str:
    """Add an event for a kid. /kid_add <kid> <event_type> <date> [time] [location]"""
    args = context.args or []
    if len(args) < 3:
        return (
            "Usage: /kid_add <kid> <event> <date> [time] [location]\n"
            "Example: /kid_add maddox Basketball practice 2026-03-25 5pm Parker Rec"
        )

    kid = args[0].lower()
    if kid not in ("maddox", "asher"):
        return "Kid must be 'maddox' or 'asher'."

    # Use AI to parse the rest of the arguments
    from pa.core.tier import Tier
    raw = " ".join(args[1:])
    PARSE = """Parse this kid's event. Return ONLY JSON:
{"event_type": "practice|game|school|appointment|other", "title": "...", "date": "YYYY-MM-DD", "time": "HH:MM or null", "location": "... or null"}
Today is """ + datetime.date.today().isoformat() + ". Raw JSON only."

    result = await ctx.brain.query(raw, system_prompt=PARSE, tier=Tier.FAST, use_conversation=False)
    try:
        import json
        import re
        result = re.sub(r',\s*([}\]])', r'\1', result.strip())
        start = result.find('{')
        end = result.rfind('}')
        if start == -1:
            raise ValueError("No JSON found")
        data = json.loads(result[start:end + 1])
    except Exception:
        return "Couldn't parse that event. Try: /kid_add maddox Basketball practice 2026-03-25 5pm"

    await ctx.store.execute(
        "INSERT INTO kids_events (kid, event_type, title, date, time, location) VALUES (?, ?, ?, ?, ?, ?)",
        (kid, data.get("event_type", "other"), data["title"], data["date"],
         data.get("time"), data.get("location")),
    )

    time_str = f" at {data['time']}" if data.get("time") else ""
    loc = f" at {data['location']}" if data.get("location") else ""
    return f"Added for {kid.capitalize()}: {data['title']} on {data['date']}{time_str}{loc}"
