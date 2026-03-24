"""Commands for the meal planning plugin."""
from __future__ import annotations

import datetime
from typing import Any

from pa.plugins import AppContext


def _week_range() -> tuple[str, str]:
    """Return (monday, sunday) ISO dates for the current week."""
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


async def handle_meals(ctx: AppContext, update: Any, context: Any) -> str:
    """Show this week's meal plan."""
    start, end = _week_range()
    rows = await ctx.store.fetchall(
        "SELECT * FROM meals_plan WHERE date >= ? AND date <= ? ORDER BY date, "
        "CASE meal_type WHEN 'breakfast' THEN 1 WHEN 'lunch' THEN 2 WHEN 'dinner' THEN 3 WHEN 'snack' THEN 4 END",
        (start, end),
    )
    if not rows:
        return "No meals planned this week. Use /meal to add one."

    lines = ["This week's meal plan:"]
    current_date = None
    for r in rows:
        if r["date"] != current_date:
            current_date = r["date"]
            d = datetime.date.fromisoformat(current_date)
            lines.append(f"\n{d.strftime('%A %m/%d')}:")
        notes = f" ({r['notes']})" if r["notes"] else ""
        lines.append(f"  {r['meal_type'].capitalize()}: {r['description']}{notes}")
    return "\n".join(lines)


async def handle_meal(ctx: AppContext, update: Any, context: Any) -> str:
    """Plan a meal. /meal <day> <type> <description>"""
    args = context.args or []
    if len(args) < 3:
        return (
            "Usage: /meal <day> <type> <description>\n"
            "Example: /meal monday dinner Tacos\n"
            "Example: /meal tomorrow lunch Leftover pasta"
        )

    from pa.core.tier import Tier
    raw = " ".join(args)
    today = datetime.date.today()
    PARSE = """Parse this meal plan entry. Return ONLY JSON:
{"date": "YYYY-MM-DD", "meal_type": "breakfast|lunch|dinner|snack", "description": "...", "notes": "... or null"}
Today is """ + today.isoformat() + f" ({today.strftime('%A')}). Raw JSON only."

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
        return "Couldn't parse that. Try: /meal monday dinner Tacos"

    meal_date = data["date"]
    meal_type = data["meal_type"]
    description = data["description"]
    notes = data.get("notes")

    # Upsert — replace if same date+type exists
    await ctx.store.execute(
        "INSERT INTO meals_plan (date, meal_type, description, notes) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(date, meal_type) DO UPDATE SET description = excluded.description, notes = excluded.notes",
        (meal_date, meal_type, description, notes),
    )

    d = datetime.date.fromisoformat(meal_date)
    return f"Planned {meal_type} for {d.strftime('%A %m/%d')}: {description}"


async def handle_grocery(ctx: AppContext, update: Any, context: Any) -> str:
    """View the grocery list (unchecked items)."""
    rows = await ctx.store.fetchall(
        "SELECT * FROM meals_grocery WHERE checked = 0 ORDER BY category, item",
    )
    if not rows:
        return "Grocery list is empty. Use /grocery_add to add items."

    lines = ["Grocery list:"]
    current_cat = None
    for r in rows:
        cat = r["category"] or "other"
        if cat != current_cat:
            current_cat = cat
            lines.append(f"\n{cat.capitalize()}:")
        qty = f" ({r['quantity']})" if r["quantity"] else ""
        lines.append(f"  [ ] {r['item']}{qty}")
    return "\n".join(lines)


async def handle_grocery_add(ctx: AppContext, update: Any, context: Any) -> str:
    """Add item to grocery list. /grocery_add <item> [quantity]"""
    args = context.args or []
    if not args:
        return "Usage: /grocery_add <item> [quantity]\nExample: /grocery_add Milk 1 gallon"

    # Simple parse: last arg could be quantity if it looks like one
    raw = " ".join(args)
    from pa.core.tier import Tier
    PARSE = """Parse this grocery item. Return ONLY JSON:
{"item": "item name", "quantity": "quantity or null", "category": "produce|dairy|meat|bakery|frozen|pantry|beverage|household|other"}
Raw JSON only."""

    result = await ctx.brain.query(raw, system_prompt=PARSE, tier=Tier.FAST, use_conversation=False)
    try:
        import json
        import re
        result = re.sub(r',\s*([}\]])', r'\1', result.strip())
        start = result.find('{')
        end = result.rfind('}')
        if start == -1:
            raise ValueError("No JSON")
        data = json.loads(result[start:end + 1])
    except Exception:
        # Fallback: just use the raw text as item name
        data = {"item": raw, "quantity": None, "category": "other"}

    await ctx.store.execute(
        "INSERT INTO meals_grocery (item, quantity, category) VALUES (?, ?, ?)",
        (data["item"], data.get("quantity"), data.get("category", "other")),
    )
    qty = f" ({data['quantity']})" if data.get("quantity") else ""
    return f"Added to grocery list: {data['item']}{qty}"


async def handle_grocery_done(ctx: AppContext, update: Any, context: Any) -> str:
    """Check off a grocery item. /grocery_done <item>"""
    args = context.args or []
    if not args:
        return "Usage: /grocery_done <item>\nExample: /grocery_done Milk"

    item_name = " ".join(args)
    count = await ctx.store.execute_rowcount(
        "UPDATE meals_grocery SET checked = 1 WHERE LOWER(item) LIKE ? AND checked = 0",
        (f"%{item_name.lower()}%",),
    )
    if count > 0:
        return f"Checked off: {item_name}"
    return f"Couldn't find '{item_name}' on the grocery list."
