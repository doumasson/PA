"""Kid Activity Tracker plugin for Maddox and Asher."""
from pathlib import Path

from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.kids.commands import handle_kids, handle_maddox, handle_asher, handle_kid_add
from pa.plugins.kids.nl import handle_kids_nl
from pa.plugins.kids.jobs import get_kids_jobs

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_NL_KEYWORDS = [
    "maddox", "asher", "the boys", "the kids",
    "soccer", "basketball", "practice", "game",
    "school", "pickup", "pick up",
]


class KidsPlugin(PluginBase):
    name = "kids"
    description = "Kid activity tracker for Maddox (12, basketball) and Asher (10, soccer)"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="kids", description="This week's events for both kids", handler=handle_kids),
            Command(name="maddox", description="Maddox's events and notes", handler=handle_maddox),
            Command(name="asher", description="Asher's events and notes", handler=handle_asher),
            Command(name="kid_add", description="Add a kid event", handler=handle_kid_add),
        ]

    def jobs(self) -> list:
        return get_kids_jobs()

    def nl_handlers(self) -> list:
        return [
            NLHandler(
                keywords=_NL_KEYWORDS,
                handler=handle_kids_nl,
                description="Questions about Maddox or Asher — schedules, events, school, sports, pickup",
                priority=14,
                intent_id="kids.schedule",
                examples=["when is Maddox's next game", "does Asher have practice today", "what are the boys doing this weekend"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return "Kid tracker for Maddox (12, basketball) and Asher (10, soccer)."
