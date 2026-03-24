"""Tasks plugin — task/todo manager for Albus."""
from pathlib import Path

from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.tasks.commands import handle_todo, handle_todos, handle_done, handle_cancel
from pa.plugins.tasks.nl import handle_task_nl
from pa.plugins.tasks.jobs import get_task_jobs

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class TasksPlugin(PluginBase):
    name = "tasks"
    description = "Task and todo manager with reminders"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(name="todo", description="Add a task", handler=handle_todo),
            Command(name="todos", description="List pending tasks", handler=handle_todos),
            Command(name="done", description="Mark task complete", handler=handle_done),
            Command(name="cancel", description="Cancel a task", handler=handle_cancel),
        ]

    def jobs(self) -> list:
        return get_task_jobs()

    def nl_handlers(self) -> list:
        return [
            NLHandler(
                keywords=[
                    "remind me", "don't forget", "need to", "gotta",
                    "remember to", "add task", "todo", "to do", "to-do",
                ],
                handler=handle_task_nl,
                description="Add a task from natural language",
                priority=12,
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Task manager active. Steven can say 'remind me to X' or 'todo X' "
            "to add tasks. Use /todos to see pending tasks."
        )
