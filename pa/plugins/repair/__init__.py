"""Repair plugin — the self-repair loop's in-process half.

Queues recurring failures from the error ledger, relays the repair daemon's
proposed patches to Telegram for approval, and records the verdicts. The
out-of-process half (tools/repair_daemon.py via albus-repair.timer) does the
dangerous work: Claude Code diagnosis in a scratch worktree, then
apply+test+restart after approval.
"""
from pathlib import Path

from pa.plugins import Callback, Command, Job, NLHandler, PluginBase
from pa.plugins.repair.commands import handle_repair_callback, handle_repairs
from pa.plugins.repair.jobs import job_repair_notify, job_repair_scan

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class RepairPlugin(PluginBase):
    name = "repair"
    description = "Self-repair: diagnose recurring failures, propose patches for approval"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return _SCHEMA_PATH.read_text(encoding="utf-8")

    def commands(self) -> list[Command]:
        return [
            Command(
                name="repairs",
                description="Show the self-repair queue",
                handler=handle_repairs,
            ),
        ]

    def jobs(self) -> list[Job]:
        return [
            Job(name="repair_scan", handler=job_repair_scan,
                trigger="interval", kwargs={"minutes": 15}),
            Job(name="repair_notify", handler=job_repair_notify,
                trigger="interval", kwargs={"minutes": 2}),
        ]

    def callbacks(self) -> list[Callback]:
        return [
            Callback(
                prefix="repair",
                handler=handle_repair_callback,
                description="Approve/reject proposed self-repair patches",
            ),
        ]

    def nl_handlers(self) -> list[NLHandler]:
        return []

    def system_prompt_fragment(self) -> str:
        return (
            "Self-repair is active: recurring failures are diagnosed by a "
            "repair daemon which proposes code patches; the user approves or "
            "rejects them via inline buttons. /repairs shows the queue."
        )
