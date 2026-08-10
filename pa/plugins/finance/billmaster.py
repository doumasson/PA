"""Bill Mastery — Albus knows every bill, when it's due, and catches the
recurring ones the owner never told it about.

Pure SQL/Python analysis over finance_transactions. ZERO LLM calls.

  - discover_from_transactions: recurring charges (weekly / biweekly /
    monthly / quarterly cadence) whose merchant doesn't fuzzy-match any
    tracked finance_bills row.
  - job_bill_discovery: weekly sweep — each NEW candidate gets exactly ONE
    Telegram approval message with Track / Not-a-bill buttons.
  - handle_billmaster_callback: the button handler ("track:<id>" /
    "dismiss:<id>").
  - infer_missing_due_dates: back-fill NULL due_dates on tracked bills from
    their transaction history.
  - handle_bills_audit: /bills_audit — the full "what do I owe and when"
    master view.
"""
import calendar
import datetime
import json
import statistics
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from pa.plugins.finance.guardian import (
    HIKE_CADENCE_MAX,
    HIKE_CADENCE_MIN,
    normalize_merchant,
)

# Tunables
LOOKBACK_DAYS = 183             # ~6 months of history
FUZZY_RATIO = 0.8               # SequenceMatcher ratio for "same merchant"
SUBSTRING_MIN_LEN = 4           # substring match only for names this long

# Cadence bands: (frequency, min avg gap days, max avg gap days, min charges).
# Monthly reuses guardian's 25-35 day subscription window and needs only 2
# charges; the rest need 3 to avoid coincidences.
_CADENCE_BANDS = [
    ("weekly", 5, 10, 3),
    ("biweekly", 11, 18, 3),
    ("monthly", HIKE_CADENCE_MIN, HIKE_CADENCE_MAX, 2),
    ("quarterly", 80, 100, 3),
]

_STEP_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12, "annual": 12}
_STEP_DAYS = {"weekly": 7, "biweekly": 14}

# Convert a bill amount to its monthly-equivalent obligation.
_MONTHLY_FACTOR = {
    "weekly": 52 / 12, "biweekly": 26 / 12, "monthly": 1.0,
    "quarterly": 1 / 3, "yearly": 1 / 12, "annual": 1 / 12,
}


# -- name matching --------------------------------------------------------------


def _merchant_key(name: str) -> str:
    """normalize_merchant, then drop pure-punctuation tokens left behind by
    stripped digits (e.g. 'NETFLIX.COM 866-555-0100' -> 'NETFLIX.COM')."""
    s = normalize_merchant(name)
    return " ".join(t for t in s.split() if any(c.isalnum() for c in t))


def _names_match(a: str, b: str) -> bool:
    """Fuzzy merchant/bill-name match: normalize both sides, then accept an
    exact match, a substring hit (shorter side >= 4 chars), or a high
    SequenceMatcher ratio."""
    ka, kb = _merchant_key(a), _merchant_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    shorter, longer = sorted((ka, kb), key=len)
    if len(shorter) >= SUBSTRING_MIN_LEN and shorter in longer:
        return True
    return SequenceMatcher(None, ka, kb).ratio() >= FUZZY_RATIO


# -- date arithmetic ------------------------------------------------------------


def _add_months(d: datetime.date, n: int) -> datetime.date:
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    return datetime.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _step(d: datetime.date, frequency: str) -> datetime.date:
    if frequency in _STEP_DAYS:
        return d + datetime.timedelta(days=_STEP_DAYS[frequency])
    return _add_months(d, _STEP_MONTHS[frequency])


def _next_due(last: datetime.date, frequency: str, today: datetime.date) -> datetime.date:
    """Last charge + cadence, rolled forward until it's not in the past."""
    due = _step(last, frequency)
    while due < today:
        due = _step(due, frequency)
    return due


def _clamp_day(d: datetime.date, day: int) -> datetime.date:
    return d.replace(day=min(day, calendar.monthrange(d.year, d.month)[1]))


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


# -- discovery ------------------------------------------------------------------


async def _recent_merchant_groups(store) -> dict[str, list[dict[str, Any]]]:
    """Non-pending debits from the last 6 months, grouped by merchant key,
    each group ordered by date."""
    since = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    rows = await store.fetchall(
        """SELECT date, description, amount
           FROM finance_transactions
           WHERE amount > 0 AND is_pending = 0 AND date >= ?
           ORDER BY date, id""",
        (since,),
    )
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = _merchant_key(r["description"])
        if key:
            groups[key].append(r)
    return groups


async def discover_from_transactions(store) -> list[dict[str, Any]]:
    """Find recurring charges NOT already tracked in finance_bills.

    A merchant qualifies with >= 2 charges at a 25-35 day cadence (monthly)
    or >= 3 charges at weekly/biweekly/quarterly cadence over the last 6
    months, provided its normalized name doesn't fuzzy-match any tracked
    bill. Pure SQL/statistics — zero LLM.
    """
    today = datetime.date.today()
    groups = await _recent_merchant_groups(store)
    bill_names = [b["name"] for b in await store.fetchall("SELECT name FROM finance_bills")]

    candidates: list[dict[str, Any]] = []
    for merchant, txns in sorted(groups.items()):
        if any(_names_match(merchant, name) for name in bill_names):
            continue  # already tracked
        dates = [datetime.date.fromisoformat(t["date"]) for t in txns]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        if not gaps:
            continue
        avg_gap = sum(gaps) / len(gaps)
        frequency = next(
            (freq for freq, lo, hi, min_charges in _CADENCE_BANDS
             if lo <= avg_gap <= hi and len(txns) >= min_charges),
            None,
        )
        if frequency is None:
            continue
        amounts = [t["amount"] for t in txns]
        median_amt = statistics.median(amounts)
        # Real bills charge a consistent amount; frequent-but-variable
        # spending (fast food, gas) is not a bill. Sub-monthly cadences get
        # a strict consistency gate; monthly/quarterly a looser one.
        spread = max(amounts) - min(amounts)
        tolerance = (
            max(1.0, 0.10 * median_amt)
            if frequency in ("weekly", "biweekly")
            else max(5.0, 0.25 * median_amt)
        )
        if spread > tolerance:
            continue
        # Fees and interest are recurring costs, not schedulable bills —
        # the Money Guardian is the right lens for those.
        lowered = merchant.lower()
        if any(w in lowered for w in ("late fee", "interest charge", "annual fee",
                                      "payroll", "direct dep", "deposit")):
            continue
        amount = round(median_amt, 2)
        typical_day = int(statistics.median(d.day for d in dates))
        next_due = _next_due(dates[-1], frequency, today)
        candidates.append({
            "merchant": merchant,
            "amount": amount,
            "frequency": frequency,
            "typical_day": typical_day,
            "next_due": next_due.isoformat(),
            "evidence": json.dumps({
                "charges": len(txns),
                "first": dates[0].isoformat(),
                "last": dates[-1].isoformat(),
                "avg_gap_days": round(avg_gap, 1),
                "typical_day": typical_day,
            }),
        })
    return candidates


async def infer_missing_due_dates(store) -> int:
    """Back-fill due_date on finance_bills rows that have a frequency but no
    due date, using the bill's own transaction history (fuzzy name match).
    Bills with no matching transactions are left NULL. Returns rows updated."""
    bills = await store.fetchall(
        "SELECT id, name, frequency FROM finance_bills "
        "WHERE due_date IS NULL AND frequency IS NOT NULL AND frequency != ''"
    )
    if not bills:
        return 0

    today = datetime.date.today()
    groups = await _recent_merchant_groups(store)
    updated = 0
    for bill in bills:
        freq = (bill["frequency"] or "").lower()
        if freq not in _STEP_MONTHS and freq not in _STEP_DAYS:
            continue
        dates = sorted(
            datetime.date.fromisoformat(t["date"])
            for merchant, txns in groups.items()
            if _names_match(merchant, bill["name"])
            for t in txns
        )
        if not dates:
            continue  # no transaction evidence — leave NULL
        due = _next_due(dates[-1], freq, today)
        if freq in _STEP_MONTHS:
            # Snap to the typical day-of-month seen in history.
            typical_day = int(statistics.median(d.day for d in dates))
            adjusted = _clamp_day(due, typical_day)
            if adjusted < today:
                adjusted = _clamp_day(_add_months(adjusted, _STEP_MONTHS[freq]), typical_day)
            due = adjusted
        await store.execute(
            "UPDATE finance_bills SET due_date = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (due.isoformat(), bill["id"]),
        )
        updated += 1
    return updated


# -- weekly job -----------------------------------------------------------------


async def job_bill_discovery(ctx) -> None:
    """Weekly bill-discovery sweep — pure SQL, zero LLM.

    Back-fills missing due dates, then records newly discovered recurring
    charges as candidates. Each candidate triggers exactly ONE approval
    message, the first time it's seen; the UNIQUE merchant column keeps
    accepted/dismissed/pending candidates from ever being re-suggested."""
    await infer_missing_due_dates(ctx.store)
    for c in await discover_from_transactions(ctx.store):
        inserted = await ctx.store.execute_rowcount(
            "INSERT OR IGNORE INTO finance_bill_candidates "
            "(merchant, amount, frequency, next_due, evidence) VALUES (?, ?, ?, ?, ?)",
            (c["merchant"], c["amount"], c["frequency"], c["next_due"], c["evidence"]),
        )
        if inserted <= 0:
            continue  # already suggested once — stay silent
        row = await ctx.store.fetchone(
            "SELECT id FROM finance_bill_candidates WHERE merchant = ?",
            (c["merchant"],),
        )
        if c["frequency"] in _STEP_MONTHS:
            due_day = datetime.date.fromisoformat(c["next_due"]).day
            when = f"next around the {_ordinal(due_day)}"
        else:
            when = f"next around {c['next_due']}"
        await ctx.bot.send_approval(
            f"\U0001f4a1 Looks like a recurring bill you're not tracking: "
            f"{c['merchant'].title()} ~${c['amount']:,.2f} {c['frequency']}, "
            f"{when}. Track it?",
            approve_data=f"billmaster:track:{row['id']}",
            reject_data=f"billmaster:dismiss:{row['id']}",
            approve_label="➕ Track it",
            reject_label="\U0001f648 Not a bill",
        )


# -- callback -------------------------------------------------------------------


async def handle_billmaster_callback(ctx, update, payload: str) -> str:
    """Inline-button handler for "billmaster:track:<id>" / "billmaster:dismiss:<id>"."""
    action, _, cid = payload.partition(":")
    if action not in ("track", "dismiss") or not cid.isdigit():
        return "That bill action made no sense to me."
    row = await ctx.store.fetchone(
        "SELECT * FROM finance_bill_candidates WHERE id = ?", (int(cid),)
    )
    if row is None:
        return f"Bill candidate #{cid} no longer exists."
    name = row["merchant"].title()
    if row["status"] != "pending":
        return f"{name} was already {row['status']}."

    if action == "dismiss":
        await ctx.store.execute(
            "UPDATE finance_bill_candidates SET status = 'dismissed' WHERE id = ?",
            (row["id"],),
        )
        return f"\U0001f648 Got it — {name} won't be suggested again."

    await ctx.store.execute(
        "INSERT INTO finance_bills (name, amount, due_date, frequency, source, paid_this_cycle) "
        "VALUES (?, ?, ?, ?, 'discovered', 0) "
        "ON CONFLICT(name) DO UPDATE SET amount=excluded.amount, "
        "due_date=excluded.due_date, frequency=excluded.frequency, "
        "source='discovered', updated_at=CURRENT_TIMESTAMP",
        (name, row["amount"], row["next_due"], row["frequency"]),
    )
    await ctx.store.execute(
        "UPDATE finance_bill_candidates SET status = 'accepted' WHERE id = ?",
        (row["id"],),
    )
    amt = f" ~${row['amount']:,.2f}" if row["amount"] else ""
    due = f", due {row['next_due']}" if row["next_due"] else ""
    freq = f" {row['frequency']}" if row["frequency"] else ""
    return f"➕ Now tracking {name}{amt}{freq}{due}."


# -- /bills_audit ---------------------------------------------------------------


async def handle_bills_audit(ctx, update, context) -> str:
    """The master 'what do I owe and when' view: every tracked bill sorted by
    next due date, total monthly obligation, missing-due-date flags, pending
    candidates, and the dismissed count."""
    today = datetime.date.today()
    bills = await ctx.store.fetchall(
        "SELECT * FROM finance_bills ORDER BY due_date IS NULL, due_date, name"
    )
    pending = await ctx.store.fetchall(
        "SELECT * FROM finance_bill_candidates WHERE status = 'pending' "
        "ORDER BY next_due, merchant"
    )
    row = await ctx.store.fetchone(
        "SELECT COUNT(*) AS n FROM finance_bill_candidates WHERE status = 'dismissed'"
    )
    dismissed = row["n"] if row else 0

    lines = [f"\U0001f4cb Bill Audit — {today.isoformat()}", ""]

    if not bills:
        lines.append("No bills tracked yet. Use /bill_add, or accept a discovery suggestion.")
    else:
        monthly_total = 0.0
        missing_due: list[str] = []
        lines.append(f"Tracked bills ({len(bills)}):")
        for b in bills:
            freq = (b["frequency"] or "monthly").lower()
            amt = f"${b['amount']:,.2f}" if b["amount"] else "amount ?"
            if b["amount"]:
                monthly_total += b["amount"] * _MONTHLY_FACTOR.get(freq, 1.0)
            if b["due_date"]:
                try:
                    days = (datetime.date.fromisoformat(b["due_date"]) - today).days
                    when = ("today" if days == 0
                            else f"in {days}d" if days > 0
                            else f"{-days}d overdue")
                except ValueError:
                    when = "?"
                paid = " ✅ paid" if b["paid_this_cycle"] else ""
                lines.append(f"  • {b['name']}: {amt} {freq}, due {b['due_date']} ({when}){paid}")
            else:
                missing_due.append(b["name"])
                lines.append(f"  • {b['name']}: {amt} {freq} — ⚠️ no due date")
        lines.append("")
        lines.append(f"Total monthly obligation: ~${monthly_total:,.2f}")
        if missing_due:
            lines.append(
                f"⚠️ Missing due dates ({len(missing_due)}): "
                + ", ".join(missing_due)
            )

    if pending:
        lines.append("")
        lines.append(f"\U0001f4a1 Pending candidates ({len(pending)}) — awaiting your Track/Dismiss:")
        for c in pending:
            amt = f"~${c['amount']:,.2f}" if c["amount"] else "amount ?"
            lines.append(
                f"  • {c['merchant'].title()}: {amt} {c['frequency'] or '?'} "
                f"(next {c['next_due'] or '?'})"
            )

    if dismissed:
        lines.append("")
        lines.append(f"\U0001f648 Dismissed candidates: {dismissed}")

    return "\n".join(lines)
