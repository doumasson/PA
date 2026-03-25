"""Natural language handler for kids plugin."""
from __future__ import annotations

import datetime
import json
import re
from typing import Any

from telegram import Update

from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_kids_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Handle natural language queries about the kids."""
    tl = text.lower()
    today = datetime.date.today()

    # Handle corrections about the kids without API calls
    # e.g. "Asher is a soccer player" / "Maddox plays basketball, not soccer"
    if any(p in tl for p in ["is a ", "plays ", "is the ", "does ", "doesn't play", "not soccer", "not basketball"]):
        kid = "asher" if "asher" in tl else "maddox" if "maddox" in tl else None
        if kid:
            await ctx.store.execute(
                "INSERT INTO kids_notes (kid, note, category) VALUES (?, ?, 'correction')",
                (kid, text.strip()[:200]),
            )
            # Also save as a preference so the system learns
            await ctx.brain.learn_preference(text.strip()[:200], learned_from="kids_correction")
            return f"Got it — noted about {kid.capitalize()}. I'll remember that."
        return None  # Not about a specific kid, let other handlers try

    # Determine intent via Haiku
    PARSE = """Parse this message about kids (Maddox, 12, basketball; Asher, 10, soccer).
Return ONLY JSON:
{"intent": "query|add|note", "kid": "maddox|asher|both|null", "event_type": "practice|game|school|appointment|other|null", "title": "... or null", "date": "YYYY-MM-DD or null", "time": "HH:MM or null", "location": "... or null", "note": "... or null"}
Today is """ + today.isoformat() + """. "the boys" or "the kids" means both.
Raw JSON only."""

    result = await ctx.brain.query(text, system_prompt=PARSE, tier=Tier.FAST, use_conversation=False)
    try:
        result = re.sub(r',\s*([}\]])', r'\1', result.strip())
        start = result.find('{')
        end = result.rfind('}')
        if start == -1:
            raise ValueError("No JSON")
        data = json.loads(result[start:end + 1])
    except Exception:
        return "I couldn't understand that. Try something like 'When's Maddox's next game?' or 'Asher has soccer at 5pm Saturday'."

    intent = data.get("intent", "query")
    kid = data.get("kid")

    if intent == "add":
        if not kid or kid in ("both", "null"):
            return "Which kid is this for — Maddox or Asher?"
        await ctx.store.execute(
            "INSERT INTO kids_events (kid, event_type, title, date, time, location) VALUES (?, ?, ?, ?, ?, ?)",
            (kid, data.get("event_type") or "other", data.get("title") or "Event",
             data.get("date"), data.get("time"), data.get("location")),
        )
        time_str = f" at {data['time']}" if data.get("time") else ""
        loc = f" at {data['location']}" if data.get("location") else ""
        return f"Got it — added for {kid.capitalize()}: {data.get('title', 'Event')} on {data.get('date', 'TBD')}{time_str}{loc}"

    if intent == "note":
        if not kid or kid in ("both", "null"):
            return "Which kid is this note for — Maddox or Asher?"
        note_text = data.get("note") or text
        await ctx.store.execute(
            "INSERT INTO kids_notes (kid, note, category) VALUES (?, ?, ?)",
            (kid, note_text, data.get("event_type") or "general"),
        )
        return f"Noted for {kid.capitalize()}."

    # Query intent
    if kid and kid not in ("both", "null"):
        events = await ctx.store.fetchall(
            "SELECT * FROM kids_events WHERE kid = ? AND date >= ? ORDER BY date, time LIMIT 5",
            (kid, today.isoformat()),
        )
    else:
        events = await ctx.store.fetchall(
            "SELECT * FROM kids_events WHERE date >= ? ORDER BY date, time LIMIT 10",
            (today.isoformat(),),
        )

    if not events:
        name = kid.capitalize() if kid and kid not in ("both", "null") else "the boys"
        return f"No upcoming events for {name}."

    lines = []
    for e in events:
        k = e["kid"].capitalize()
        time_str = f" at {e['time']}" if e["time"] else ""
        loc = f" — {e['location']}" if e["location"] else ""
        lines.append(f"• {e['date']} {k}: {e['title']}{time_str}{loc}")
    return "\n".join(lines)
