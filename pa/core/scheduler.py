from typing import Any, Callable, Awaitable
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pa.plugins import Job

# Global context store — set at startup, accessed by job runners
_CTX = None

async def _heartbeat_handler(job_name: str = "heartbeat") -> None:
    """Module-level heartbeat handler."""
    if _CTX and hasattr(_CTX, 'bot'):
        from pa.core.identity import NAME
        # Only send heartbeat, don't spam
        pass

async def _job_dispatcher(job_name: str = "unknown") -> None:
    """Module-level job dispatcher — routes job_name to the right handler."""
    global _CTX
    if _CTX is None:
        return
    ctx = _CTX

    try:
        if job_name == "morning_sync":
            from pa.plugins.finance.jobs import job_morning_sync
            await job_morning_sync(ctx)

        elif job_name == "balance_check":
            from pa.plugins.finance.jobs import job_balance_check
            await job_balance_check(ctx)

        elif job_name == "due_date_check":
            from pa.plugins.finance.jobs import job_due_date_check
            await job_due_date_check(ctx)

        elif job_name == "weekly_advisor":
            from pa.plugins.finance.jobs import job_weekly_advisor
            await job_weekly_advisor(ctx)

        elif job_name == "teller_morning":
            from pa.plugins.teller.jobs import morning_sync
            await morning_sync(ctx)

        elif job_name == "teller_weekly":
            from pa.plugins.teller.jobs import weekly_sync
            await weekly_sync(ctx)

        elif job_name in ("gmail_check_6am", "gmail_check_10am",
                          "gmail_check_2pm", "gmail_check_6pm"):
            from pa.plugins.google.jobs import check_gmail
            await check_gmail(ctx)

        elif job_name == "heartbeat":
            pass

        else:
            print(f"Unknown job: {job_name}")

    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"Job {job_name} error: {error_msg}")
        try:
            sql = "INSERT INTO agent_lessons (lesson, source) VALUES (?, ?)"
            await ctx.store.execute(sql, (f"Job {job_name} failed: {str(e)[:500]}", "system_error"))
        except Exception:
            pass
        try:
            if ctx.bot:
                await ctx.bot.send_message(f"System error in {job_name}: {str(e)[:200]}")
        except Exception:
            pass


class PAScheduler:
    def __init__(self):
        self._scheduler = AsyncScheduler()
        self._jobs: list[Job] = []
        self._alert_handler: Callable[..., Awaitable] | None = None
        self._paused = False
        self._jobs.append(Job(
            name="heartbeat",
            handler=_heartbeat_handler,
            trigger="cron",
            kwargs={"hour": 12, "minute": 0},
        ))

    def set_ctx(self, ctx) -> None:
        global _CTX
        _CTX = ctx

    def register_job(self, job: Job) -> None:
        self._jobs.append(job)

    def register_alert_handler(self, handler: Callable[..., Awaitable]) -> None:
        self._alert_handler = handler

    async def start(self) -> None:
        await self._scheduler.__aenter__()
        for job in self._jobs:
            if job.trigger == "interval":
                trigger = IntervalTrigger(
                    hours=job.kwargs.get("hours", 0),
                    minutes=job.kwargs.get("minutes", 0),
                )
            else:
                trigger_kwargs = {k: v for k, v in job.kwargs.items()}
                trigger = CronTrigger(**trigger_kwargs)
            await self._scheduler.add_schedule(
                _job_dispatcher, trigger, id=job.name, args=[job.name]
            )
        await self._scheduler.start_in_background()

    async def stop(self) -> None:
        await self._scheduler.__aexit__(None, None, None)

    def get_job_names(self) -> list[str]:
        return [j.name for j in self._jobs]

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False
