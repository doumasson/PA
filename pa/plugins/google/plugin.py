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

CREATE TABLE IF NOT EXISTS google_notified_emails (
    message_id TEXT PRIMARY KEY,
    subject_snippet TEXT,
    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                          "doing soccer", "doing basketball", "doing baseball",
                          "plays basketball", "plays soccer", "plays football",
                          "is the soccer", "is the basketball", "is the football",
                          "soccer player", "basketball player", "football player",
                          "doesn't play", "not maddox", "not asher",
                          "is soccer", "is basketball", "is football"],
                handler=handle_kid_sport,
                description="Update what sport a kid plays",
                priority=19,
                intent_id="google.kid_sport",
                examples=["Maddox now plays soccer", "Asher switched to basketball", "Maddox doesn't play football anymore"],
            ),
            NLHandler(
                keywords=["stop sending", "don't send", "dont send", "stop showing",
                          "don't care about", "dont care about", "block email",
                          "mute email", "filter out", "not interested in",
                          "stop telling me about", "no more emails about"],
                handler=handle_email_block,
                description="Block or mute email notifications from a sender or topic",
                priority=17,
                intent_id="google.email_block",
                examples=["stop sending me emails about promotions", "block emails from LinkedIn", "I don't care about newsletter emails"],
            ),
            NLHandler(
                keywords=["bills", "scan bills", "find my bills", "bill scan", "scrape bills"],
                handler=lambda ctx, text, update: __import__('pa.plugins.google.bills', fromlist=['run_bill_extraction']).run_bill_extraction(ctx),
                priority=12,
                intent_id="google.bill_scan",
                description="Scan Gmail for recurring bills and extract bill information",
                examples=["scan my email for bills", "find my bills in Gmail", "what bills do I have"],
            ),
            NLHandler(
                keywords=["email", "gmail", "inbox", "message", "mail", "important", "anything important"],
                handler=handle_gmail_nl,
                priority=10,
                intent_id="google.email",
                description="Check email, Gmail inbox, unread messages, important or critical emails",
                examples=["any important emails", "check my inbox", "any critical emails in the last few days"],
            ),
            NLHandler(
                keywords=["calendar", "schedule", "appointment"],
                handler=handle_gmail_nl,
                priority=8,
                intent_id="google.calendar",
                description="Check calendar events, appointments, schedule",
                examples=["what's on my calendar today", "any appointments this week", "what's my schedule"],
            ),
        ]

    def system_prompt_fragment(self) -> str:
        return (
            "Gmail and Calendar integration active. You can check emails with /gmail "
            "and calendar events are created automatically from important emails."
        )
