"""Health and Habit Tracking plugin for Albus."""
from pathlib import Path

from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.health.commands import handle_log, handle_health, handle_goal
from pa.plugins.health.nl import handle_health_nl
from pa.plugins.health.jobs import get_health_jobs

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class HealthPlugin(PluginBase):
    name = "health"
    description = "Health and habit tracking — exercise, sleep, water, weight, mood, steps"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="log", description="Log health entry", handler=handle_log),
            Command(name="health", description="Weekly health summary", handler=handle_health),
            Command(name="goal", description="Set a health goal", handler=handle_goal),
        ]

    def jobs(self) -> list:
        return get_health_jobs()

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=[
                    "i ran", "i walked", "i slept", "hours of sleep",
                    "i weigh", "my weight", "i drank", "glasses of water",
                    "worked out", "went to gym", "exercised", "feeling",
                ],
                handler=handle_health_nl,
                description="Log health data — exercise, sleep, weight, water intake, mood, gym activity",
                priority=12,
                intent_id="health.log",
                examples=["I ran 3 miles today", "slept 6 hours last night", "I weigh 185"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Health tracker active. Steven can say 'I ran 3 miles' or "
            "'slept 6 hours' to log health data. Use /health for weekly summary."
        )
