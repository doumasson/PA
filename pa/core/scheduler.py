"""Job scheduler — plugins register jobs, scheduler dispatches via registry."""
from typing import Any, Callable, Awaitable
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pa.plugins import Job

_CTX = None
_JOB_REGISTRY: dict[str, Callable] = {}


async def _job_dispatcher(job_name: str = "unknown") -> None:
    """Dispatch jobs by name from the registry — no hardcoded if/elif."""
    global _CTX
    if _CTX is None:
        return

    handler = _JOB_REGISTRY.get(job_name)
    if handler is None:
        print(f"Unknown job: {job_name}")
        return

    try:
        await handler(_CTX)
    except Exception as e:
        import traceback
        print(f"Job {job_name} error: {traceback.format_exc()}")
        # Self-healing: log error to DB
        try:
            await _CTX.store.execute(
                """INSERT INTO core_errors (source, error_type, message, last_seen)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT DO NOTHING""",
                (f"job:{job_name}", type(e).__name__, str(e)[:500])
            )
        except Exception:
            pass
        # Notify user
        try:
            if _CTX.bot:
                await _CTX.bot.send_message(f"Job {job_name} failed: {str(e)[:200]}")
        except Exception:
            pass


class PAScheduler:
    def __init__(self):
        self._scheduler = AsyncScheduler()
        self._jobs: list[Job] = []
        self._alert_handler: Callable[..., Awaitable] | None = None

    def set_ctx(self, ctx) -> None:
        global _CTX
        _CTX = ctx

    def register_job(self, job: Job) -> None:
        self._jobs.append(job)
        _JOB_REGISTRY[job.name] = job.handler

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
