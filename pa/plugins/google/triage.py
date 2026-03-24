"""Email triage using Claude - classifies emails in batches."""
from __future__ import annotations
import json
import logging
from pa.core.tier import Tier

log = logging.getLogger(__name__)

SYSTEM = """You are an email triage assistant for a busy dad named Steven.
He has two sons: Maddox (12) and Asher (10) who play soccer and basketball.

Classify each email and respond ONLY with a valid JSON array. No markdown, no backticks, no explanation. Raw JSON only.

For each email return:
{"id":"email id","category":"action"|"event"|"important"|"noise","urgency":"high"|"normal"|"low","summary":"max 15 words","notify":true|false,"calendar_event":null|{"title":"...","date":"YYYY-MM-DD or null","time":"HH:MM or null","duration_minutes":60,"location":"..."}}

Rules:
- noise = promotions, newsletters, marketing, social media, automated receipts under $100
- action = needs Steven's response or decision
- event = has specific date/time (sports, appointments, school events)
- important = useful info but no action needed (large transactions, shipping, account alerts)
- notify = true only for: action+high, any event, important+high
- calendar_event = only for category event with extractable date
- Kids sports title format: "Asher Soccer" or "Maddox Basketball"
- ALWAYS flag as action+high: charge-off warnings, past due, overdraft, fraud, anything urgent from a bank
- Water/utility bills = important+normal
- School newsletters = noise, but specific notices about Maddox or Asher = important
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
        msg = f"Classify these {len(batch)} emails as a JSON array:\n\n{email_list}"

        try:
            text = await brain.query(
                msg, system_prompt=system_override or SYSTEM,
                tier=Tier.FAST, use_conversation=False,
            )
            text = text.strip()
            # Strip any markdown fences
            if '```' in text:
                parts = text.split('```')
                for part in parts[1:]:
                    if part.strip().startswith('json'):
                        text = part.strip()[4:].strip()
                        break
                    elif part.strip().startswith('['):
                        text = part.strip()
                        break
            # Find the JSON array
            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1:
                text = text[start:end+1]
            # Fix common JSON issues from LLM output
            text = text.replace(',]', ']').replace(',}', '}')
            # Try to fix trailing commas and missing quotes
            import re
            text = re.sub(r',\s*([}\]])', r'\1', text)
            results = json.loads(text)
            if isinstance(results, list):
                all_results.extend(results)
        except json.JSONDecodeError as e:
            log.warning("Triage batch %d JSON error: %s", i // batch_size, e)
            # Fall back to classifying each email individually
            for email in batch:
                try:
                    single = await brain.query(
                        f"Classify this email as a JSON array with one element:\n\n{_format_email(email)}",
                        system_prompt=system_override or SYSTEM,
                        tier=Tier.FAST, use_conversation=False,
                    )
                    single = single.strip()
                    start = single.find('[')
                    end = single.rfind(']')
                    if start != -1 and end != -1:
                        single = single[start:end+1]
                    import re
                    single = re.sub(r',\s*([}\]])', r'\1', single)
                    parsed = json.loads(single)
                    if isinstance(parsed, list):
                        all_results.extend(parsed)
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
