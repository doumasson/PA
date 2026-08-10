"""Job scheduler v2 — instance-based (no module globals), ledger-guarded.

Every job runs through the error ledger: failures are recorded with a
signature, deduplicated, and surfaced to the owner with a friendly message.
Friendly-message mapping stays because "invalid_grant" means nothing at 7am.
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Awaitable, Callable

from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pa.plugins import Job

logger = logging.getLogger(__name__)


def _harden_apscheduler():
    """Stop apscheduler 4.0.0a6 from crashing its scheduler task group.

    On a race it calls release_job twice for one job; the second
    self._jobs_by_id.pop(result.job_id) raises KeyError, which propagates out
    of the scheduler task group and kills it, leaving pa a zombie (Telegram
    bot dead, jobs stopped) until the watchdog restarts it. The job is already
    gone, so swallowing that KeyError is correct and keeps the scheduler alive.
    """
    try:
        from apscheduler.datastores.memory import MemoryDataStore
    except Exception:
        return
    if getattr(MemoryDataStore, "_rh_hardened", False):
        return
    _orig = MemoryDataStore.release_job

    async def _safe_release(self, scheduler_id, job, result):
        try:
            return await _orig(self, scheduler_id, job, result)
        except KeyError:
            logger.warning("apscheduler double-released a job -- ignored")
            return None

    MemoryDataStore.release_job = _safe_release
    MemoryDataStore._rh_hardened = True
    logger.info("apscheduler release_job hardened against double-release KeyError")


_harden_apscheduler()

_FRIENDLY_ERRORS: dict[str, str] = {
    "401": "Bank connection expired. Use /sync to reconnect.",
    "oauth": "Bank connection expired. Use /sync to reconnect.",
    "token_expired": "Bank connection expired. Use /sync to reconnect.",
    "invalid_grant": "Gmail connection expired. Re-run tools/google_auth.py on the Pi to reconnect.",
    "refresh_token": "Gmail connection expired. Re-run tools/google_auth.py on the Pi to reconnect.",
    "timeout": "Couldn't reach the service. Will retry next check.",
    "timed out": "Couldn't reach the service. Will retry next check.",
    "connectionerror": "Couldn't reach the service. Will retry next check.",
}


def friendly_error(job_name: str, error: Exception) -> str:
    err_str = str(error).lower()
    for pattern, friendly in _FRIENDLY_ERRORS.items():
        if pattern in err_str:
            return friendly
    return f"Something went wrong with {job_name}. Check /errors for details."


class PAScheduler:
    NOTIFY_COOLDOWN_S = 86400  # same source+type at most daily

    def __init__(self, ledger=None, timezone: str | None = None):
        self._scheduler = AsyncScheduler()
        self._jobs: list[Job] = []
        self._registry: dict[str, Callable[..., Awaitable]] = {}
        self._ctx = None
        self._ledger = ledger
        self._timezone = timezone
        self._last_run: dict[str, str] = {}
        self._last_success: dict[str, str] = {}
        self._recent_notifications: dict[tuple[str, str], float] = {}

    def set_ctx(self, ctx) -> None:
        self._ctx = ctx

    def register_job(self, job: Job) -> None:
        self._jobs.append(job)
        self._registry[job.name] = job.handler

    async def start(self) -> None:
        import threading
        await self._scheduler.__aenter__()
        for job in self._jobs:
            await self._schedule(job.name, job.trigger, job.kwargs)
        await self._scheduler.start_in_background()
        self._stopping = False
        self._hb_ts = time.monotonic()
        # Heartbeat is a scheduled job: it updates _hb_ts every 60 s, so it
        # stops the instant the scheduler dies. That silence is the signal.
        await self._scheduler.add_schedule(
            self._heartbeat, IntervalTrigger(seconds=60),
            id="scheduler_heartbeat")
        # The watchdog runs in a REAL OS THREAD, never an asyncio task. When
        # apscheduler 4.0.0a6 crashes its task group (KeyError in job-result
        # bookkeeping, ~every balance_check) it wedges the whole event loop —
        # so an asyncio-based watchdog dies with it (that is why the 2026-07-08
        # version never fired and pa zombied for 6 h). A daemon thread with
        # time.sleep keeps ticking regardless and hard-exits so systemd
        # (Restart=on-failure) revives pa within seconds.
        threading.Thread(target=self._watchdog_thread, daemon=True,
                         name="scheduler-watchdog").start()

    async def _heartbeat(self) -> None:
        self._hb_ts = time.monotonic()

    def _watchdog_thread(self) -> None:
        import os
        while True:
            time.sleep(30)
            if getattr(self, "_stopping", False):
                return
            if time.monotonic() - self._hb_ts > 200:
                logger.critical(
                    "Scheduler heartbeat stale >200s (scheduler wedged) — "
                    "hard-exiting 70 so systemd restarts pa")
                os._exit(70)

    async def stop(self) -> None:
        self._stopping = True
        await self._scheduler.__aexit__(None, None, None)

    async def add_dynamic_job(
        self, name: str, handler: Callable, trigger: str, kwargs: dict
    ) -> None:
        self._registry[name] = handler
        await self._schedule(name, trigger, kwargs)

    async def remove_dynamic_job(self, name: str) -> None:
        try:
            await self._scheduler.remove_schedule(name)
        except Exception:
            logger.info("No schedule %r to remove", name)
        self._registry.pop(name, None)

    def get_job_names(self) -> list[str]:
        return list(self._registry)

    def last_run(self, name: str) -> str | None:
        return self._last_run.get(name)

    def last_success(self, name: str) -> str | None:
        return self._last_success.get(name)

    # -- internals ----------------------------------------------------------

    async def _schedule(self, name: str, trigger: str, kwargs: dict) -> None:
        if trigger == "interval":
            hours = kwargs.get("hours", 0)
            minutes = kwargs.get("minutes", 0)
            # First fire after one full period rather than at boot. Interval
            # jobs all slamming at startup is what tickled APScheduler a6's
            # scheduler-killing race (slow balance_check, 2026-07-08).
            start = datetime.datetime.now(datetime.timezone.utc) + \
                datetime.timedelta(hours=hours, minutes=minutes)
            t = IntervalTrigger(hours=hours, minutes=minutes, start_time=start)
        else:
            # Pin cron jobs to the owner's timezone so "7am" is 7am local
            # regardless of the Pi's OS clock (which may be UTC).
            ck = dict(kwargs)
            if self._timezone and "timezone" not in ck:
                ck["timezone"] = self._timezone
            t = CronTrigger(**ck)
        await self._scheduler.add_schedule(
            self._dispatch, t, id=name, args=[name]
        )

    async def _dispatch(self, job_name: str) -> None:
        handler = self._registry.get(job_name)
        if handler is None:
            logger.error("Unknown job dispatched: %r", job_name)
            return
        if self._ctx is None:
            logger.error("Job %r fired before context was wired", job_name)
            return
        self._last_run[job_name] = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            await handler(self._ctx)
            # last_success only after the handler actually returns — a hang or
            # crash leaves it stale so an overdue-sweep can spot the silence.
            self._last_success[job_name] = datetime.datetime.now().isoformat(timespec="seconds")
        except Exception as e:
            source = f"job:{job_name}"
            if self._ledger is not None:
                await self._ledger.record(e, source=source)
            else:
                logger.exception("Job %r failed (no ledger wired)", job_name)
            await self._notify_friendly(source, job_name, e)

    async def _notify_friendly(self, source: str, job_name: str, e: Exception) -> None:
        bot = getattr(self._ctx, "bot", None)
        if bot is None:
            return
        key = (source, type(e).__name__)
        now = time.time()
        if now - self._recent_notifications.get(key, 0) < self.NOTIFY_COOLDOWN_S:
            return
        self._recent_notifications[key] = now
        try:
            await bot.send_message(friendly_error(job_name, e))
        except Exception:
            logger.exception("Could not deliver job-failure notification")
