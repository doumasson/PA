"""Tasks plugin — task/todo manager for Albus."""
import logging
from pathlib import Path

from pa.plugins import AppContext, PluginBase, Command, NLHandler
from pa.plugins.tasks.commands import handle_todo, handle_todos, handle_done, handle_cancel
from pa.plugins.tasks.nl import (
    handle_task_nl, handle_task_close_nl, handle_task_list_nl, _recurring_trigger,
)
from pa.plugins.tasks.jobs import get_task_jobs

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
log = logging.getLogger(__name__)


class TasksPlugin(PluginBase):
    name = "tasks"
    description = "Task and todo manager with reminders"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    async def on_startup(self, ctx: AppContext) -> None:
        # Dynamic recurring jobs live only in the in-memory scheduler, so every
        # restart (including the ones the repair daemon performs) used to wipe
        # them while the DB still claimed they recurred. Re-register here.
        if not ctx.scheduler:
            return
        rows = await ctx.store.fetchall(
            "SELECT id, title, due_date, recurring, due_time FROM tasks_items "
            "WHERE recurring IS NOT NULL AND status = 'pending'"
        )
        for r in rows:
            hour, minute = 8, 0
            if r["due_time"]:
                try:
                    hour, minute = (int(x) for x in r["due_time"].split(":")[:2])
                except ValueError:
                    pass
            trigger, kwargs = _recurring_trigger(
                r["recurring"], hour, minute, None, r["due_date"]
            )

            async def _alert(_ctx, _title=r["title"], _id=r["id"]):
                await _ctx.bot.send_message(f"⏰ Recurring reminder: {_title} (#{_id})")

            try:
                await ctx.scheduler.add_dynamic_job(
                    f"recurring_task_{r['id']}", _alert, trigger, kwargs
                )
            except Exception as e:
                log.warning("Could not re-register recurring task %s: %s", r["id"], e)

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
                description="Add a task, reminder, or todo item",
                priority=12,
                intent_id="tasks.reminder",
                examples=["remind me to call the dentist", "I need to pick up the kids at 5", "add to my todo list: fix the sink"],
            ),
            NLHandler(
                keywords=[
                    "kill the", "cancel the", "delete the", "done with",
                    "finished", "already did", "mark done", "no longer need",
                    "not relevant anymore",
                ],
                handler=handle_task_close_nl,
                description=(
                    "Mark a pending task/reminder done, or kill/cancel one that "
                    "is stale or no longer relevant"
                ),
                priority=13,
                intent_id="tasks.complete",
                examples=["kill the track and alert weekly task", "I already paid the IRS bill", "cancel that reminder about the sink"],
            ),
            NLHandler(
                keywords=["my tasks", "my todos", "what's pending", "overdue tasks", "task list"],
                handler=handle_task_list_nl,
                description="List pending tasks/reminders, including overdue ones",
                priority=11,
                intent_id="tasks.list",
                examples=["what's on my task list", "anything overdue?"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Task manager active. The user can say 'remind me to X' or 'todo X' "
            "to add tasks. Use /todos to see pending tasks."
        )
