from pa.plugins import Job


def get_finance_jobs() -> list[Job]:
    async def noop(job_name: str) -> None:
        pass

    return [
        Job(name="bank_balance", handler=noop, trigger="interval", kwargs={"hours": 4}),
        Job(name="cc_balance", handler=noop, trigger="cron", kwargs={"hour": 6, "minute": 0}),
        Job(name="transaction_pull", handler=noop, trigger="cron", kwargs={"hour": 7, "minute": 0}),
        Job(name="due_date_check", handler=noop, trigger="cron", kwargs={"hour": 8, "minute": 0}),
        Job(name="weekly_summary", handler=noop, trigger="cron", kwargs={"day_of_week": "sun", "hour": 19, "minute": 0}),
        Job(name="monthly_report", handler=noop, trigger="cron", kwargs={"day": 1, "hour": 9, "minute": 0}),
    ]
