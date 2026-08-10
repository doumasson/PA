"""Money Guardian — proactive anomaly detection over transaction data.

Pure SQL/Python analysis. ZERO LLM calls. Three detectors:
  1. Duplicate charges — same merchant + amount billed twice within days.
  2. Price hikes — near-monthly merchants (subscriptions) whose latest
     charge jumped versus the median of prior charges.
  3. New merchants — first-ever charge from a merchant, over a threshold.

Each finding carries a stable sha256 fingerprint; fingerprints already in
finance_guardian_alerts have been alerted and never fire again.
"""
import datetime
import hashlib
import re
import statistics
from collections import defaultdict
from typing import Any

# Tunables
DUPLICATE_MIN_AMOUNT = 5.0      # ignore tiny duplicate charges
DUPLICATE_WINDOW_DAYS = 4       # two charges this close = suspect
DUPLICATE_LOOKBACK_DAYS = 30
HIKE_LOOKBACK_DAYS = 183        # ~6 months
HIKE_MIN_OCCURRENCES = 3
HIKE_CADENCE_MIN = 25           # average gap (days) for "near-monthly"
HIKE_CADENCE_MAX = 35
HIKE_MIN_INCREASE_ABS = 2.0     # flag if increase > max($2, 5%)
HIKE_MIN_INCREASE_PCT = 0.05
NEW_MERCHANT_DAYS = 3
NEW_MERCHANT_MIN_AMOUNT = 75.0


def normalize_merchant(description: str) -> str:
    """Normalize a raw transaction description to a merchant key.

    Uppercase, strip digits/#/* (which also removes trailing store
    numbers), collapse whitespace.
    """
    s = description.upper()
    s = re.sub(r"[0-9#*]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fingerprint(*parts: Any) -> str:
    """Stable fingerprint for a finding: sha256 over its identity parts."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


async def find_duplicate_charges(store) -> list[dict[str, Any]]:
    """Same normalized merchant AND same amount (>= $5) charged 2+ times
    within a 4-day window in the last 30 days. Distinct dedup_hash rows,
    not pending."""
    since = (datetime.date.today() - datetime.timedelta(days=DUPLICATE_LOOKBACK_DAYS)).isoformat()
    rows = await store.fetchall(
        """SELECT date, description, amount, dedup_hash
           FROM finance_transactions
           WHERE amount >= ? AND is_pending = 0 AND date >= ?
           ORDER BY date, id""",
        (DUPLICATE_MIN_AMOUNT, since),
    )

    groups: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        merchant = normalize_merchant(r["description"])
        if merchant:
            groups[(merchant, round(r["amount"], 2))].append(r)

    findings: list[dict[str, Any]] = []
    for (merchant, amount), txns in groups.items():
        if len(txns) < 2:
            continue
        # Distinct dedup_hash rows only (the UNIQUE constraint already
        # guarantees row-level distinctness, this is belt and braces).
        distinct = sorted(
            {t["dedup_hash"]: t for t in txns}.values(), key=lambda t: t["date"]
        )
        for a, b in zip(distinct, distinct[1:]):
            d1 = datetime.date.fromisoformat(a["date"])
            d2 = datetime.date.fromisoformat(b["date"])
            days = (d2 - d1).days
            if days > DUPLICATE_WINDOW_DAYS:
                continue
            when = f"twice within {days} days" if days else f"twice on {a['date']}"
            findings.append({
                "kind": "duplicate",
                "merchant": merchant,
                "amount": amount,
                "dates": [a["date"], b["date"]],
                "fingerprint": _fingerprint(
                    "duplicate", merchant, f"{amount:.2f}", a["date"], b["date"]
                ),
                "message": (
                    f"Possible duplicate: {merchant} charged ${amount:,.2f} {when}"
                    f" ({a['date']} / {b['date']})"
                ),
            })
    return findings


async def find_price_hikes(store) -> list[dict[str, Any]]:
    """Merchants appearing >= 3 times in 6 months with near-monthly cadence
    (25-35 day average gaps): flag if the latest amount exceeds the median
    of prior amounts by more than max($2, 5%). Catches subscription creep."""
    since = (datetime.date.today() - datetime.timedelta(days=HIKE_LOOKBACK_DAYS)).isoformat()
    rows = await store.fetchall(
        """SELECT date, description, amount
           FROM finance_transactions
           WHERE amount > 0 AND is_pending = 0 AND date >= ?
           ORDER BY date, id""",
        (since,),
    )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        merchant = normalize_merchant(r["description"])
        if merchant:
            groups[merchant].append(r)

    findings: list[dict[str, Any]] = []
    for merchant, txns in groups.items():
        if len(txns) < HIKE_MIN_OCCURRENCES:
            continue
        dates = [datetime.date.fromisoformat(t["date"]) for t in txns]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        avg_gap = sum(gaps) / len(gaps)
        if not (HIKE_CADENCE_MIN <= avg_gap <= HIKE_CADENCE_MAX):
            continue
        latest = txns[-1]["amount"]
        prior_median = statistics.median(t["amount"] for t in txns[:-1])
        increase = latest - prior_median
        if increase <= max(HIKE_MIN_INCREASE_ABS, HIKE_MIN_INCREASE_PCT * prior_median):
            continue
        pct = increase / prior_median * 100
        findings.append({
            "kind": "hike",
            "merchant": merchant,
            "old_amount": round(prior_median, 2),
            "new_amount": round(latest, 2),
            "fingerprint": _fingerprint(
                "hike", merchant, f"{prior_median:.2f}", f"{latest:.2f}"
            ),
            "message": (
                f"Subscription creep: {merchant} was ~${prior_median:,.2f}, "
                f"now ${latest:,.2f} (+{pct:.0f}%)"
            ),
        })
    return findings


async def find_new_merchants(store) -> list[dict[str, Any]]:
    """Merchants first seen in the last 3 days with a charge >= $75."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=NEW_MERCHANT_DAYS)).isoformat()
    rows = await store.fetchall(
        """SELECT date, description, amount
           FROM finance_transactions
           WHERE amount > 0 AND is_pending = 0
           ORDER BY date, id""",
    )

    first_seen: dict[str, str] = {}
    biggest_recent: dict[str, dict[str, Any]] = {}
    for r in rows:  # ordered by date, so first hit = first seen
        merchant = normalize_merchant(r["description"])
        if not merchant:
            continue
        first_seen.setdefault(merchant, r["date"])
        if r["date"] >= cutoff and r["amount"] >= NEW_MERCHANT_MIN_AMOUNT:
            cur = biggest_recent.get(merchant)
            if cur is None or r["amount"] > cur["amount"]:
                biggest_recent[merchant] = r

    findings: list[dict[str, Any]] = []
    for merchant, txn in biggest_recent.items():
        if first_seen[merchant] < cutoff:
            continue  # known merchant, not new
        findings.append({
            "kind": "new_merchant",
            "merchant": merchant,
            "amount": round(txn["amount"], 2),
            "date": txn["date"],
            "fingerprint": _fingerprint(
                "new_merchant", merchant, f"{txn['amount']:.2f}", txn["date"]
            ),
            "message": (
                f"New merchant: {merchant} charged ${txn['amount']:,.2f} on {txn['date']}"
            ),
        })
    return findings


async def run_checks(store) -> list[dict[str, Any]]:
    """Run all guardian detectors and return the combined findings."""
    findings: list[dict[str, Any]] = []
    findings.extend(await find_duplicate_charges(store))
    findings.extend(await find_price_hikes(store))
    findings.extend(await find_new_merchants(store))
    return findings


async def record_new_findings(store, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """INSERT OR IGNORE each fingerprint; return only genuinely-new findings."""
    new: list[dict[str, Any]] = []
    for f in findings:
        inserted = await store.execute_rowcount(
            "INSERT OR IGNORE INTO finance_guardian_alerts (fingerprint, kind, detail) "
            "VALUES (?, ?, ?)",
            (f["fingerprint"], f["kind"], f["message"]),
        )
        if inserted > 0:
            new.append(f)
    return new


async def get_alerted_fingerprints(store) -> set[str]:
    rows = await store.fetchall("SELECT fingerprint FROM finance_guardian_alerts")
    return {r["fingerprint"] for r in rows}


async def job_guardian_check(ctx) -> None:
    """Daily guardian sweep — pure SQL, zero API calls.

    Computes findings, records fingerprints, and sends ONE combined
    Telegram message for genuinely-new findings. Silent when nothing new.
    """
    findings = await run_checks(ctx.store)
    new = await record_new_findings(ctx.store, findings)
    if not new:
        return
    lines = ["\U0001f6e1 Money Guardian:"]
    lines.extend(f"• {f['message']}" for f in new)
    await ctx.bot.send_message("\n".join(lines))
