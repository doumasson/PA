"""Email triage using Claude - classifies emails in batches."""
from __future__ import annotations
import json
from pa.core.tier import Tier

SYSTEM = """You are an email triage assistant for a busy dad named Shane.
He has two sons: Maddox (12) and Asher (10) who play soccer and basketball.

Classify each email and respond ONLY with a valid JSON array. No markdown, no backticks, no explanation. Raw JSON only.

For each email return:
{"id":"email id","category":"action"|"event"|"important"|"noise","urgency":"high"|"normal"|"low","summary":"max 15 words","notify":true|false,"calendar_event":null|{"title":"...","date":"YYYY-MM-DD or null","time":"HH:MM or null","duration_minutes":60,"location":"..."}}

Rules:
- noise = promotions, newsletters, marketing, social media, automated receipts under $100
- action = needs Shane's response or decision
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
    batch_size = 10

    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        email_list = "\n\n".join(
            f'ID:{e["id"]}\nFrom:{e["sender"]}\nSubject:{e["subject"]}\nPreview:{e["snippet"]}'
            for e in batch
        )
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
            print(f"Triage batch {i//batch_size} JSON error: {e}")
            # Try individual email fallback
            for email in batch:
                all_results.append({
                    "id": email["id"],
                    "category": "noise",
                    "urgency": "low",
                    "summary": email.get("subject", "")[:50],
                    "notify": False,
                    "calendar_event": None,
                })
            continue
        except Exception as e:
            print(f"Triage batch {i//batch_size} error: {e}")
            continue

    return all_results
