from typing import Any, Callable, Awaitable

from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pa.plugins import Job


class PAScheduler:
    def __init__(self):
        self._scheduler = AsyncScheduler()
        self._jobs: list[Job] = []
        self._alert_handler: Callable[..., Awaitable] | None = None
        self._paused = False
        self._jobs.append(Job(
            name="heartbeat",
            handler=self._heartbeat,
            trigger="cron",
            kwargs={"hour": 12, "minute": 0},
        ))

    async def _heartbeat(self, job_name: str = "heartbeat") -> None:
        if self._alert_handler:
            await self._alert_handler(job_name)

    def register_job(self, job: Job) -> None:
        self._jobs.append(job)

    def register_alert_handler(self, handler: Callable[..., Awaitable]) -> None:
        self._alert_handler = handler

    async def start(self) -> None:
        await self._scheduler.__aenter__()
        for job in self._jobs:
            handler = job.handler
            if job.trigger == "interval":
                trigger = IntervalTrigger(
                    hours=job.kwargs.get("hours", 4),
                    jitter=job.kwargs.get("jitter", 0),
                )
            else:
                trigger_kwargs = {k: v for k, v in job.kwargs.items()}
                trigger = CronTrigger(**trigger_kwargs)
            await self._scheduler.add_schedule(
                handler, trigger, id=job.name, args=[job.name]
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

    @property
    def is_paused(self) -> bool:
        return self._paused
