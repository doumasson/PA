"""Natural language handler for meals plugin."""
from __future__ import annotations

import datetime
import json
import re

from telegram import Update

from pa.plugins import AppContext
from pa.core.tier import Tier


async def handle_meals_nl(ctx: AppContext, text: str, update: Update) -> str:
    """Handle natural language queries about meals and groceries."""
    today = datetime.date.today()

    PARSE = """Parse this message about meals or groceries. Return ONLY JSON:
{"intent": "query_meal|add_meal|query_grocery|add_grocery|check_grocery|clear_grocery",
 "date": "YYYY-MM-DD or null",
 "meal_type": "breakfast|lunch|dinner|snack|null",
 "description": "meal description or null",
 "items": ["grocery item 1", "grocery item 2"] or [],
 "item_name": "item to check off or null"}
Today is """ + today.isoformat() + f" ({today.strftime('%A')}). Raw JSON only."

    result = await ctx.brain.query(text, system_prompt=PARSE, tier=Tier.FAST, use_conversation=False)
    try:
        result = re.sub(r',\s*([}\]])', r'\1', result.strip())
        start = result.find('{')
        end = result.rfind('}')
        if start == -1:
            raise ValueError("No JSON")
        data = json.loads(result[start:end + 1])
    except Exception:
        return "I couldn't understand that. Try 'What's for dinner?' or 'Add milk to the grocery list'."

    intent = data.get("intent", "query_meal")

    if intent == "query_meal":
        meal_date = data.get("date") or today.isoformat()
        meal_type = data.get("meal_type")
        if meal_type:
            row = await ctx.store.fetchone(
                "SELECT * FROM meals_plan WHERE date = ? AND meal_type = ?",
                (meal_date, meal_type),
            )
            if row:
                return f"{meal_type.capitalize()} for {meal_date}: {row['description']}"
            return f"No {meal_type} planned for {meal_date}. Want to plan something?"
        else:
            rows = await ctx.store.fetchall(
                "SELECT * FROM meals_plan WHERE date = ? ORDER BY "
                "CASE meal_type WHEN 'breakfast' THEN 1 WHEN 'lunch' THEN 2 "
                "WHEN 'dinner' THEN 3 WHEN 'snack' THEN 4 END",
                (meal_date,),
            )
            if rows:
                lines = [f"Meals for {meal_date}:"]
                for r in rows:
                    lines.append(f"• {r['meal_type'].capitalize()}: {r['description']}")
                return "\n".join(lines)
            return f"No meals planned for {meal_date}."

    if intent == "add_meal":
        meal_date = data.get("date") or today.isoformat()
        meal_type = data.get("meal_type") or "dinner"
        description = data.get("description")
        if not description:
            return "What's the meal? Try 'Tacos for dinner tonight'."
        await ctx.store.execute(
            "INSERT INTO meals_plan (date, meal_type, description) VALUES (?, ?, ?) "
            "ON CONFLICT(date, meal_type) DO UPDATE SET description = excluded.description",
            (meal_date, meal_type, description),
        )
        d = datetime.date.fromisoformat(meal_date)
        return f"Planned {meal_type} for {d.strftime('%A %m/%d')}: {description}"

    if intent == "add_grocery":
        items = data.get("items") or []
        if not items:
            return "What should I add to the grocery list?"
        for item in items:
            await ctx.store.execute(
                "INSERT INTO meals_grocery (item, category) VALUES (?, 'other')",
                (item,),
            )
        if len(items) == 1:
            return f"Added to grocery list: {items[0]}"
        return f"Added {len(items)} items to grocery list: {', '.join(items)}"

    if intent == "query_grocery":
        rows = await ctx.store.fetchall(
            "SELECT * FROM meals_grocery WHERE checked = 0 ORDER BY category, item",
        )
        if not rows:
            return "Grocery list is empty."
        lines = ["Grocery list:"]
        for r in rows:
            qty = f" ({r['quantity']})" if r["quantity"] else ""
            lines.append(f"• {r['item']}{qty}")
        return "\n".join(lines)

    if intent == "check_grocery":
        item_name = data.get("item_name")
        if not item_name:
            return "Which item should I check off?"
        count = await ctx.store.execute_rowcount(
            "UPDATE meals_grocery SET checked = 1 WHERE LOWER(item) LIKE ? AND checked = 0",
            (f"%{item_name.lower()}%",),
        )
        if count > 0:
            return f"Checked off: {item_name}"
        return f"Couldn't find '{item_name}' on the grocery list."

    if intent == "clear_grocery":
        count = await ctx.store.execute_rowcount(
            "UPDATE meals_grocery SET checked = 1 WHERE checked = 0",
            (),
        )
        if count == 0:
            return "Grocery list is already empty — nothing to clear."
        return f"Cleared {count} item{'s' if count != 1 else ''} from your grocery list."

    return "I'm not sure what you mean. Try 'What's for dinner?' or 'Add eggs to the grocery list'."
