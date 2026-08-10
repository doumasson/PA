"""Meal Planning and Grocery Lists plugin."""
import logging
from pathlib import Path

from pa.plugins import AppContext, PluginBase, Command, NLHandler
from pa.plugins.meals.commands import (
    handle_meals, handle_meal, handle_grocery, handle_grocery_add, handle_grocery_done,
    handle_grocery_clear,
)
from pa.plugins.meals.nl import handle_meals_nl
from pa.plugins.meals.jobs import get_meals_jobs, _STATE_KEY_IGNORED, _STATE_KEY_ENGAGED

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_NL_KEYWORDS = [
    "what's for dinner", "what should we eat", "meal plan",
    "grocery list", "need to buy", "pick up from store",
    "add to grocery", "shopping list", "whats for lunch",
    "whats for dinner",
    "clear grocery", "clear shopping", "clear the list", "clear my list",
    "empty the list", "done shopping", "check off everything",
    "delete grocery", "wipe the list",
    "ordered", "having for dinner", "making for dinner",
    "cooking", "i ordered", "we ordered", "getting pizza",
    "having pizza", "eating", "i ate", "we ate",
]


class MealsPlugin(PluginBase):
    name = "meals"
    description = "Meal planning and grocery list management"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="meals", description="This week's meal plan", handler=handle_meals),
            Command(name="meal", description="Plan a meal", handler=handle_meal),
            Command(name="grocery", description="View grocery list", handler=handle_grocery),
            Command(name="grocery_add", description="Add to grocery list", handler=handle_grocery_add),
            Command(name="grocery_done", description="Check off grocery item", handler=handle_grocery_done),
            Command(name="grocery_clear", description="Clear grocery list", handler=handle_grocery_clear),
        ]

    def jobs(self) -> list:
        return get_meals_jobs()

    def nl_handlers(self) -> list:
        return [
            NLHandler(
                keywords=_NL_KEYWORDS,
                handler=handle_meals_nl,
                description="Meal planning, recording meals eaten/ordered, dinner ideas, grocery/shopping list management",
                priority=10,
                intent_id="meals.plan",
                examples=["what's for dinner tonight", "I ordered pizza", "we're having tacos", "add milk to the grocery list", "clear my shopping list"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return "Meal planner active. The user can plan meals, manage grocery lists, and ask 'what's for dinner?'"

    async def on_startup(self, ctx: AppContext) -> None:
        """One-time migration: the dinner-nag counter used to live in the
        google plugin's google_state table. Copy any meal-related keys into
        meals_state (INSERT OR IGNORE so an existing value is never clobbered)."""
        try:
            rows = await ctx.store.fetchall(
                "SELECT key, value FROM google_state WHERE key IN (?, ?)",
                (_STATE_KEY_IGNORED, _STATE_KEY_ENGAGED),
            )
            for row in rows:
                await ctx.store.execute(
                    "INSERT OR IGNORE INTO meals_state (key, value) VALUES (?, ?)",
                    (row["key"], row["value"]),
                )
        except Exception:
            # google_state may not exist (google plugin absent) — that's fine.
            logger.debug("No meal state migrated from google_state", exc_info=True)
