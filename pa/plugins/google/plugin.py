from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.google.jobs import get_google_jobs
from pa.plugins.google.commands import handle_gmail_check, handle_gmail_nl


class GooglePlugin(PluginBase):
    name = "google"
    description = "Gmail triage and Google Calendar integration"
    version = "0.1.0"

    def schema_sql(self) -> str:
        return """
CREATE TABLE IF NOT EXISTS google_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

    def commands(self) -> list:
        return [
            Command(name="gmail", description="Check Gmail now", handler=handle_gmail_check),
        ]

    def jobs(self) -> list:
        return get_google_jobs()

    def nl_handlers(self) -> list:
        return [
            NLHandler(
                keywords=["bills", "scan bills", "find my bills", "bill scan", "scrape bills"],
                handler=lambda ctx, text, update: __import__('pa.plugins.google.bills', fromlist=['run_bill_extraction']).run_bill_extraction(ctx),
                priority=12,
            ),
            NLHandler(
                keywords=["email", "gmail", "inbox", "message", "mail", "important", "anything important"],
                handler=handle_gmail_nl,
                priority=10,
            ),
            NLHandler(
                keywords=["calendar", "schedule", "appointment", "game", "event"],
                handler=handle_gmail_nl,
                priority=8,
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Gmail and Calendar integration active. You can check emails with /gmail "
            "and calendar events are created automatically from important emails."
        )
