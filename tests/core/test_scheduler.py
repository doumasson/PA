from pa.core.scheduler import PAScheduler
from pa.plugins import Job


def test_default_has_heartbeat_only():
    s = PAScheduler()
    assert "heartbeat" in s.get_job_names()
    assert len(s.get_job_names()) == 1


def test_register_job():
    s = PAScheduler()
    job = Job(name="test_job", handler=lambda: None, trigger="cron", kwargs={"hour": 6})
    s.register_job(job)
    assert "test_job" in s.get_job_names()


def test_pause_resume():
    s = PAScheduler()
    assert not s.is_paused
    s.pause()
    assert s.is_paused
    s.resume()
    assert not s.is_paused
