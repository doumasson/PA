"""Research plugin — deep research and topic watchlist."""
from pathlib import Path

from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.research.handlers import (
    handle_research,
    handle_watch,
    handle_watchlist,
    handle_research_nl,
)
from pa.plugins.research.jobs import get_research_jobs

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class ResearchPlugin(PluginBase):
    name = "research"
    description = "Deep research on topics and periodic watchlist updates"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="research", description="Deep research on a topic", handler=handle_research),
            Command(name="watch", description="Add a topic to the watchlist", handler=handle_watch),
            Command(name="watchlist", description="View watched topics", handler=handle_watchlist),
        ]

    def jobs(self) -> list:
        return get_research_jobs()

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=[
                    "what's happening with", "tell me about", "research",
                    "look into", "what do you know about", "news about",
                    "latest on", "update on", "find out about",
                ],
                handler=handle_research_nl,
                description="Research a topic using Claude Sonnet",
                priority=8,
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Research agent active. Steven can say 'tell me about X' or "
            "'what's happening with Y' for deep research. Use /watch to track topics."
        )
