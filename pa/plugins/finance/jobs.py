from pa.plugins import Job


async def _finance_noop(job_name: str) -> None:
    """Placeholder handler — replaced at startup when scrape handlers are wired."""
    pass


def get_finance_jobs() -> list[Job]:
    return [
        Job(name="bank_balance", handler=_finance_noop, trigger="interval", kwargs={"hours": 4}),
        Job(name="cc_balance", handler=_finance_noop, trigger="cron", kwargs={"hour": 6, "minute": 0}),
        Job(name="transaction_pull", handler=_finance_noop, trigger="cron", kwargs={"hour": 7, "minute": 0}),
        Job(name="due_date_check", handler=_finance_noop, trigger="cron", kwargs={"hour": 8, "minute": 0}),
        Job(name="weekly_summary", handler=_finance_noop, trigger="cron", kwargs={"day_of_week": "sun", "hour": 19, "minute": 0}),
        Job(name="monthly_report", handler=_finance_noop, trigger="cron", kwargs={"day": 1, "hour": 9, "minute": 0}),
    ]
