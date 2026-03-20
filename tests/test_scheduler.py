import pytest
from unittest.mock import AsyncMock

from pa.scheduler.scheduler import PAScheduler


async def test_scheduler_creates_default_jobs():
    scheduler = PAScheduler()
    mock_scrape = AsyncMock()
    mock_alert = AsyncMock()
    scheduler.register_scrape_handler(mock_scrape)
    scheduler.register_alert_handler(mock_alert)
    job_names = scheduler.get_job_names()
    assert "bank_balance" in job_names
    assert "cc_balance" in job_names
    assert "transaction_pull" in job_names
    assert "due_date_check" in job_names
    assert "heartbeat" in job_names


async def test_scheduler_pause_resume():
    scheduler = PAScheduler()
    scheduler.register_scrape_handler(AsyncMock())
    scheduler.register_alert_handler(AsyncMock())
    scheduler.pause()
    assert scheduler.is_paused
    scheduler.resume()
    assert not scheduler.is_paused
