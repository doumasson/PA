"""Meal Planning and Grocery Lists plugin."""
from pathlib import Path

from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.meals.commands import (
    handle_meals, handle_meal, handle_grocery, handle_grocery_add, handle_grocery_done,
    handle_grocery_clear,
)
from pa.plugins.meals.nl import handle_meals_nl
from pa.plugins.meals.jobs import get_meals_jobs

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_NL_KEYWORDS = [
    "what's for dinner", "what should we eat", "meal plan",
    "grocery list", "need to buy", "pick up from store",
    "add to grocery", "shopping list", "whats for lunch",
    "whats for dinner",
    "clear grocery", "clear shopping", "clear the list", "clear my list",
    "empty the list", "done shopping", "check off everything",
    "delete grocery", "wipe the list",
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
                description="Meal planning, dinner ideas, grocery/shopping list management",
                priority=10,
                intent_id="meals.plan",
                examples=["what's for dinner tonight", "add milk to the grocery list", "clear my shopping list"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return "Meal planner active. Steven can plan meals, manage grocery lists, and ask 'what's for dinner?'"
