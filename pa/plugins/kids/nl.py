"""Natural language handler for kids plugin."""
from __future__ import annotations

import datetime

from telegram import Update

from pa.plugins import AppContext
from pa.core.brain import Tier


async def kid_names(ctx: AppContext) -> list[str]:
    """Kid names (lowercase) from the profile, falling back to the DB.

    TODO: kids_events/kids_notes still carry CHECK(kid IN ('maddox','asher'));
    inserts for kids added to the profile later will fail until that
    constraint is migrated.
    """
    profile = getattr(ctx, "profile", None)
    if profile is not None and getattr(profile, "kids", None):
        return [k.name.lower() for k in profile.kids]
    rows = await ctx.store.fetchall(
        "SELECT DISTINCT kid FROM kids_events UNION SELECT DISTINCT kid FROM kids_notes"
    )
    names = sorted(r["kid"] for r in rows if r["kid"])
    return names or ["maddox", "asher"]


def _kid_descriptions(ctx: AppContext, kids: list[str]) -> str:
    """Human-readable kid list for prompts, e.g. 'Maddox, 12, basketball'."""
    profile = getattr(ctx, "profile", None)
    parts = []
    for name in kids:
        k = profile.kid(name) if profile is not None else None
        if k is not None:
            bits = [k.name.capitalize()]
            age = k.age()
            if age is not None:
                bits.append(str(age))
            if k.notes:
                bits.append(k.notes)
            parts.append(", ".join(bits))
        else:
            parts.append(name.capitalize())
    return "; ".join(parts)


def _kid_choices(kids: list[str]) -> str:
    """'Maddox or Asher' style phrasing for clarification questions."""
    names = [k.capitalize() for k in kids]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


async def handle_kids_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Handle natural language queries about the kids."""
    tl = text.lower()
    today = datetime.date.today()
    kids = await kid_names(ctx)

    # Handle corrections about the kids without API calls
    # e.g. "Asher is a soccer player" / "Maddox plays basketball, not soccer".
    # Questions ("does Asher have practice today?") must NOT be treated as
    # corrections — only declarative statements are.
    is_question = text.strip().endswith("?") or tl.split(" ", 1)[0] in (
        "does", "do", "is", "are", "when", "what", "who", "where", "how", "did", "will"
    )
    correction_markers = ["is a ", "plays ", "is the ", "doesn't play",
                          "not soccer", "not basketball", "now plays"]
    if not is_question and any(p in tl for p in correction_markers):
        kid = next((k for k in kids if k in tl), None)
        if kid:
            await ctx.store.execute(
                "INSERT INTO kids_notes (kid, note, category) VALUES (?, ?, 'correction')",
                (kid, text.strip()[:200]),
            )
            # Also save as a preference so the system learns
            if ctx.learning:
                note = text.strip()[:200]
                await ctx.learning.remember(
                    "preference", note, {"text": note}, source="kids"
                )
            return f"Got it — noted about {kid.capitalize()}. I'll remember that."
        return None  # Not about a specific kid, let other handlers try

    # Determine intent via the parse tier
    kid_enum = "|".join(kids)
    PARSE = """Parse this message about kids (""" + _kid_descriptions(ctx, kids) + """).
Return ONLY JSON:
{"intent": "query|add|note", "kid": \"""" + kid_enum + """|both|null", "event_type": "practice|game|school|appointment|other|null", "title": "... or null", "date": "YYYY-MM-DD or null", "time": "HH:MM or null", "location": "... or null", "note": "... or null"}
Today is """ + today.isoformat() + """. "the boys" or "the kids" means both.
Raw JSON only."""

    try:
        data = await ctx.brain.query_json(text, tier=Tier.PARSE, system=PARSE)
    except ValueError:
        return "I couldn't understand that. Try something like 'When's Maddox's next game?' or 'Asher has soccer at 5pm Saturday'."

    intent = data.get("intent", "query")
    kid = data.get("kid")

    if intent == "add":
        if not kid or kid in ("both", "null"):
            return f"Which kid is this for — {_kid_choices(kids)}?"
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
            return f"Which kid is this note for — {_kid_choices(kids)}?"
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
