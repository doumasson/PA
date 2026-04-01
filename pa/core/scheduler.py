"""Job scheduler — plugins register jobs, scheduler dispatches via registry."""
from typing import Any, Callable, Awaitable
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pa.plugins import Job

_CTX = None
_JOB_REGISTRY: dict[str, Callable] = {}

# Known error → friendly message mapping
_FRIENDLY_ERRORS: dict[str, str] = {
    "401": "Bank connection expired. Use /sync to reconnect.",
    "oauth": "Bank connection expired. Use /sync to reconnect.",
    "token_expired": "Bank connection expired. Use /sync to reconnect.",
    "invalid_grant": "Gmail connection expired. Run /gmail_auth to reconnect.",
    "refresh_token": "Gmail connection expired. Run /gmail_auth to reconnect.",
    "timeout": "Couldn't reach the service. Will retry next check.",
    "timed out": "Couldn't reach the service. Will retry next check.",
    "connectionerror": "Couldn't reach the service. Will retry next check.",
}

# Track recent error notifications: (source, error_type) → timestamp
_recent_error_notifications: dict[tuple[str, str], float] = {}


def _format_error(job_name: str, error: Exception) -> str:
    """Convert raw errors to human-readable messages."""
    err_str = str(error).lower()
    for pattern, friendly in _FRIENDLY_ERRORS.items():
        if pattern in err_str:
            return friendly
    return f"Something went wrong with {job_name}. Check logs for details."


def _should_notify_error(source: str, error_type: str) -> bool:
    """Suppress duplicate error notifications within 24 hours."""
    import time
    key = (source, error_type)
    now = time.time()
    last = _recent_error_notifications.get(key, 0)
    if now - last < 86400:  # 24 hours
        return False
    _recent_error_notifications[key] = now
    return True


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
        source = f"job:{job_name}"
        error_type = type(e).__name__
        try:
            await _CTX.store.execute(
                """INSERT INTO core_errors (source, error_type, message, last_seen)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT DO NOTHING""",
                (source, error_type, str(e)[:500])
            )
        except Exception:
            pass
        # Notify user with friendly message (suppress repeats)
        try:
            if _CTX.bot and _should_notify_error(source, error_type):
                friendly = _format_error(job_name, e)
                await _CTX.bot.send_message(friendly)
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

    async def add_dynamic_job(self, name: str, handler: Callable, trigger: str, kwargs: dict) -> None:
        """Add a job at runtime (for recurring tasks, alerts, etc.)."""
        _JOB_REGISTRY[name] = handler
        if trigger == "interval":
            t = IntervalTrigger(
                hours=kwargs.get("hours", 0),
                minutes=kwargs.get("minutes", 0),
            )
        else:
            t = CronTrigger(**kwargs)
        await self._scheduler.add_schedule(
            _job_dispatcher, t, id=name, args=[name]
        )

    async def remove_dynamic_job(self, name: str) -> None:
        """Remove a dynamically added job."""
        try:
            await self._scheduler.remove_schedule(name)
        except Exception:
            pass
        _JOB_REGISTRY.pop(name, None)

    def get_job_names(self) -> list[str]:
        return [j.name for j in self._jobs] + [k for k in _JOB_REGISTRY if k not in {j.name for j in self._jobs}]
