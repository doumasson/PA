from typing import Any, Callable, Awaitable

from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


class PAScheduler:
    def __init__(self):
        self._scheduler = AsyncScheduler()
        self._job_defs: dict[str, dict[str, Any]] = {}
        self._scrape_handler: Callable[..., Awaitable] | None = None
        self._alert_handler: Callable[..., Awaitable] | None = None
        self._paused = False
        self._setup_default_jobs()

    def _setup_default_jobs(self) -> None:
        self._job_defs = {
            "bank_balance": {"type": "interval", "hours": 4, "jitter": 900},
            "cc_balance": {"type": "cron", "hour": 6, "minute": 0},
            "transaction_pull": {"type": "cron", "hour": 7, "minute": 0},
            "due_date_check": {"type": "cron", "hour": 8, "minute": 0},
            "weekly_summary": {"type": "cron", "day_of_week": "sun", "hour": 19, "minute": 0},
            "monthly_report": {"type": "cron", "day": 1, "hour": 9, "minute": 0},
            "heartbeat": {"type": "cron", "hour": 12, "minute": 0},
        }

    def register_scrape_handler(self, handler: Callable[..., Awaitable]) -> None:
        self._scrape_handler = handler

    def register_alert_handler(self, handler: Callable[..., Awaitable]) -> None:
        self._alert_handler = handler

    async def start(self) -> None:
        for name, job_def in self._job_defs.items():
            handler = self._scrape_handler if name != "heartbeat" else self._alert_handler
            if handler is None:
                continue
            if job_def["type"] == "interval":
                trigger = IntervalTrigger(
                    hours=job_def.get("hours", 4),
                    jitter=job_def.get("jitter", 0),
                )
            else:
                trigger_kwargs = {k: v for k, v in job_def.items() if k != "type"}
                trigger = CronTrigger(**trigger_kwargs)
            await self._scheduler.add_schedule(
                handler, trigger, id=name, args=[name]
            )
        await self._scheduler.start_in_background()

    async def stop(self) -> None:
        await self._scheduler.stop()

    def get_job_names(self) -> list[str]:
        return list(self._job_defs.keys())

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def update_schedule(self, job_name: str, **kwargs: Any) -> None:
        if job_name in self._job_defs:
            self._job_defs[job_name].update(kwargs)
