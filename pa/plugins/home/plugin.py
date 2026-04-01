"""Home Maintenance Tracker plugin for PA."""
from pathlib import Path

from pa.plugins import PluginBase, Command, Job, NLHandler
from pa.plugins.home.commands import handle_home, handle_home_add, handle_home_done
from pa.plugins.home.nl import handle_home_nl
from pa.plugins.home.jobs import job_home_reminders

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class HomePlugin(PluginBase):
    name = "home"
    description = "Home maintenance task tracker with reminders"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="home", description="List home maintenance tasks", handler=handle_home),
            Command(name="home_add", description="Add a maintenance task", handler=handle_home_add),
            Command(name="home_done", description="Mark a task as done", handler=handle_home_done),
        ]

    def jobs(self) -> list[Job]:
        return [
            Job(
                name="home_reminders",
                handler=job_home_reminders,
                trigger="cron",
                kwargs={"day_of_week": "mon", "hour": 8, "minute": 45},
            ),
        ]

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=[
                    "changed the filter", "replaced the", "serviced the",
                    "cleaned the", "mowed the", "last time i", "when did i",
                    "furnace", "oil change", "air filter", "water heater", "gutter",
                ],
                handler=handle_home_nl,
                description="Log home maintenance tasks or ask when something was last done",
                priority=10,
                intent_id="home.maintenance",
                examples=["I changed the furnace filter", "when did I last mow the lawn", "I replaced the air filter"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Home maintenance tracker active. Steven can say 'I changed the furnace filter' "
            "to log maintenance, or 'when did I last change the oil?' to check."
        )
