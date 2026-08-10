"""Email triage using Claude - classifies emails in batches."""
from __future__ import annotations
import logging
from pa.core.brain import Tier

log = logging.getLogger(__name__)

SYSTEM = """You are an email triage assistant for a busy parent.

Classify each email. Respond ONLY with a JSON object of the form
{"results": [...]} — one entry per email. No markdown, no backticks, no explanation.

Each entry:
{"id":"email id","category":"action"|"event"|"important"|"noise","urgency":"high"|"normal"|"low","summary":"max 15 words","notify":true|false,"calendar_event":null|{"title":"...","date":"YYYY-MM-DD or null","time":"HH:MM or null","duration_minutes":60,"location":"..."}}

Rules:
- noise = promotions, newsletters, marketing, social media, automated receipts under $100
- action = needs the user's response or decision
- event = has specific date/time (sports, appointments, school events)
- important = useful info but no action needed (large transactions, shipping, account alerts)
- notify = true only for: action+high, any event, important+high
- calendar_event = only for category event with extractable date
- Kids sports calendar title format: "<Kid name> <Sport>"
- ALWAYS flag as action+high: charge-off warnings, past due, overdraft, fraud, anything urgent from a bank
- Water/utility bills = important+normal
- School newsletters = noise, but specific notices about the user's kids = important
- When in doubt: noise"""


async def classify_emails_batch(emails: list[dict], brain, system_override: str = None) -> list[dict]:
    """Classify emails in batches of 10 to keep JSON clean."""
    if not emails:
        return []

    all_results = []
    # Smaller batches when emails have full bodies (bill emails) to keep Haiku output clean
    has_bodies = any(e.get('body') for e in emails)
    batch_size = 5 if has_bodies else 10

    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        def _format_email(e):
            lines = f'ID:{e["id"]}\nFrom:{e["sender"]}\nSubject:{e["subject"]}\nPreview:{e["snippet"]}'
            if e.get('body'):
                lines += f'\nBody (excerpt):{e["body"][:1500]}'
            return lines

        email_list = "\n\n".join(_format_email(e) for e in batch)
        msg = (
            f'Classify these {len(batch)} emails. Return a JSON object '
            f'{{"results": [...]}} with one entry per email:\n\n{email_list}'
        )

        try:
            data = await brain.query_json(
                msg, tier=Tier.PARSE,
                system=system_override or SYSTEM, max_tokens=2048,
            )
            results = data.get('results')
            if isinstance(results, list):
                all_results.extend(results)
        except ValueError as e:
            # Covers json.JSONDecodeError too — the batch reply wasn't parseable.
            log.warning("Triage batch %d JSON error: %s", i // batch_size, e)
            # Fall back to classifying each email individually
            for email in batch:
                try:
                    single = await brain.query_json(
                        f"Classify this email. Return ONE JSON object (the entry itself, "
                        f"not wrapped in an array):\n\n{_format_email(email)}",
                        tier=Tier.PARSE,
                        system=system_override or SYSTEM,
                    )
                    if isinstance(single, dict) and single.get('id'):
                        all_results.append(single)
                except Exception:
                    all_results.append({
                        "id": email["id"],
                        "category": "noise",
                        "urgency": "low",
                        "summary": email.get("subject", "")[:50],
                        "notify": False,
                    })
            continue
        except Exception as e:
            log.error("Triage batch %d error: %s", i // batch_size, e)
            continue

    return all_results
