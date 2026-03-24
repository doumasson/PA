from __future__ import annotations
from pathlib import Path
from pa.plugins import AppContext, Command, NLHandler, PluginBase
from pa.plugins.agent.commands import cmd_agent, handle_agent_query


class AgentPlugin(PluginBase):
    name        = "agent"
    description = "DungeonMind build agent control and memory"
    version     = "2.0.0"

    def schema_sql(self) -> str:
        return (Path(__file__).parent / "schema.sql").read_text()

    def commands(self) -> list[Command]:
        return [
            Command(
                name="agent",
                description="Control the build agent (start/stop/status/history/screenshot/lesson)",
                handler=cmd_agent,
            )
        ]

    def nl_handlers(self) -> list[NLHandler]:
        return [
            NLHandler(
                keywords=[
                    "build agent", "the agent", "the build",
                    "dungeonmind", "the game",
                ],
                handler=handle_agent_query,
                description="Control and query the DungeonMind build agent",
                priority=5,
            )
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "You control a build agent that autonomously develops a game called DungeonMind. "
            "The user can trigger it with phrases like 'start the build', 'run the agent', "
            "'build dungeonmind', 'fire up the agent'. They must reference the build/agent/game "
            "specifically — generic phrases like 'kick this off' are too vague since you do many things. "
            "Use /agent start to start, /agent stop to stop, /agent status for updates."
        )

    async def on_startup(self, ctx: AppContext) -> None:
        from pa.plugins.agent.memory import AgentMemory
        memory = AgentMemory(ctx.store)
        await memory.add_lesson(
            "Never write tests -- build game code, assets, and fixes only",
            source="system"
        )
