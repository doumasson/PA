from pa.plugins import PluginBase, Command, NLHandler
from pa.plugins.google.jobs import get_google_jobs
from pa.plugins.google.commands import (
    handle_gmail_check, handle_gmail_nl, handle_email_block,
    handle_email_blocks, handle_email_unblock, handle_kid_sport,
)


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

CREATE TABLE IF NOT EXISTS google_email_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_type TEXT NOT NULL CHECK(block_type IN ('sender', 'subject', 'keyword')),
    pattern TEXT NOT NULL UNIQUE,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

    def commands(self) -> list:
        return [
            Command(name="gmail", description="Check Gmail now", handler=handle_gmail_check),
            Command(name="email_blocks", description="View blocked email topics", handler=handle_email_blocks),
            Command(name="email_unblock", description="Unblock an email topic", handler=handle_email_unblock),
        ]

    def jobs(self) -> list:
        return get_google_jobs()

    def nl_handlers(self) -> list:
        return [
            NLHandler(
                keywords=["now plays", "now playing", "switched to", "is playing",
                          "started playing", "signed up for", "doing football",
                          "doing soccer", "doing basketball", "doing baseball"],
                handler=handle_kid_sport,
                description="Update what sport a kid plays",
                priority=19,
            ),
            NLHandler(
                keywords=["stop sending", "don't send", "dont send", "stop showing",
                          "don't care about", "dont care about", "block email",
                          "mute email", "filter out", "not interested in",
                          "stop telling me about", "no more emails about"],
                handler=handle_email_block,
                description="Block email topics/senders",
                priority=17,
            ),
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
                keywords=["calendar", "schedule", "appointment"],
                handler=handle_gmail_nl,
                priority=8,
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Gmail and Calendar integration active. You can check emails with /gmail "
            "and calendar events are created automatically from important emails."
        )
