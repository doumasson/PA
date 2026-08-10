# tests/plugins/finance/test_billmaster.py
"""Bill Mastery — real tmp SQLite Store, no LLM, no network."""
import datetime
import hashlib
import types
from pathlib import Path

import pytest

from pa.core.store import Store
from pa.plugins.finance.billmaster import (
    discover_from_transactions,
    handle_billmaster_callback,
    handle_bills_audit,
    infer_missing_due_dates,
    job_bill_discovery,
)

_FINANCE_DIR = (
    Path(__file__).parent.parent.parent.parent / "pa" / "plugins" / "finance"
)


def days_ago(n: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def days_ahead(n: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


class FakeBot:
    def __init__(self):
        self.messages: list[str] = []
        self.approvals: list[dict] = []

    async def send_message(self, text: str) -> None:
        self.messages.append(text)

    async def send_approval(self, text, approve_data, reject_data,
                            approve_label="✅ Approve", reject_label="❌ Reject") -> None:
        self.approvals.append({
            "text": text,
            "approve_data": approve_data,
            "reject_data": reject_data,
            "approve_label": approve_label,
            "reject_label": reject_label,
        })


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    await s.init_schema()
    # Full finance plugin schema: base (transactions, candidates) + advisor (bills).
    ddl = (_FINANCE_DIR / "schema.sql").read_text(encoding="utf-8")
    ddl += (_FINANCE_DIR / "advisor_schema.sql").read_text(encoding="utf-8")
    await s.init_plugin_schema("finance", ddl)
    await s.execute(
        "INSERT INTO finance_accounts (institution, name, type) VALUES (?, ?, ?)",
        ("test", "Test Checking", "checking"),
    )
    yield s
    await s.close()


@pytest.fixture
def ctx(store):
    return types.SimpleNamespace(
        store=store, bot=FakeBot(),
        vault=types.SimpleNamespace(is_unlocked=True), ledger=None,
    )


async def add_txn(store, date: str, description: str, amount: float,
                  is_pending: bool = False, salt: str = "") -> None:
    dedup = hashlib.sha256(f"1|{date}|{description}|{amount}|{salt}".encode()).hexdigest()
    await store.execute(
        "INSERT INTO finance_transactions "
        "(account_id, date, description, amount, dedup_hash, is_pending) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, date, description, amount, dedup, is_pending),
    )


async def seed_netflix(store) -> None:
    """Clear monthly recurrence: three charges, 30 days apart."""
    for n in (65, 35, 5):
        await add_txn(store, days_ago(n), "NETFLIX.COM 866-555-0100", 15.49)


# -- discovery ------------------------------------------------------------------


async def test_monthly_recurrence_becomes_candidate(store):
    await seed_netflix(store)
    # Noise: a one-off charge shouldn't qualify.
    await add_txn(store, days_ago(10), "FANCY RESTAURANT", 82.00)

    candidates = await discover_from_transactions(store)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["merchant"] == "NETFLIX.COM"
    assert c["amount"] == 15.49
    assert c["frequency"] == "monthly"
    # next_due = last charge + cadence: parseable, not in the past, near-term.
    next_due = datetime.date.fromisoformat(c["next_due"])
    today = datetime.date.today()
    assert today <= next_due <= today + datetime.timedelta(days=40)
    assert "charges" in c["evidence"]


async def test_two_weekly_charges_not_enough(store):
    # Weekly cadence needs >= 3 charges; 2 is a coincidence.
    await add_txn(store, days_ago(14), "CAR WASH CLUB", 12.00)
    await add_txn(store, days_ago(7), "CAR WASH CLUB", 12.00)
    assert await discover_from_transactions(store) == []

    # A third weekly charge tips it over.
    await add_txn(store, days_ago(0), "CAR WASH CLUB", 12.00)
    candidates = await discover_from_transactions(store)
    assert len(candidates) == 1
    assert candidates[0]["frequency"] == "weekly"


async def test_tracked_bill_fuzzy_matched_not_a_candidate(store):
    # Bill row "Netflix" vs raw merchant "NETFLIX.COM 866-555-0100".
    await store.execute(
        "INSERT INTO finance_bills (name, amount, frequency) VALUES (?, ?, ?)",
        ("Netflix", 15.49, "monthly"),
    )
    await seed_netflix(store)
    assert await discover_from_transactions(store) == []


# -- job: one approval per candidate, ever --------------------------------------


async def test_job_sends_approval_once_then_silent(store, ctx):
    await seed_netflix(store)

    await job_bill_discovery(ctx)
    assert len(ctx.bot.approvals) == 1
    a = ctx.bot.approvals[0]
    assert "recurring bill you're not tracking" in a["text"]
    assert "Netflix.Com" in a["text"]
    assert "$15.49" in a["text"]
    assert "monthly" in a["text"]
    assert a["approve_data"].startswith("billmaster:track:")
    assert a["reject_data"].startswith("billmaster:dismiss:")
    assert a["approve_label"] == "➕ Track it"

    row = await store.fetchone("SELECT * FROM finance_bill_candidates")
    assert row["merchant"] == "NETFLIX.COM"
    assert row["status"] == "pending"

    # Second run: candidate already recorded — no new approval, no dupe row.
    await job_bill_discovery(ctx)
    assert len(ctx.bot.approvals) == 1
    rows = await store.fetchall("SELECT * FROM finance_bill_candidates")
    assert len(rows) == 1


# -- callbacks ------------------------------------------------------------------


async def test_track_callback_creates_bill(store, ctx):
    await seed_netflix(store)
    await job_bill_discovery(ctx)
    cand = await store.fetchone("SELECT * FROM finance_bill_candidates")

    out = await handle_billmaster_callback(ctx, None, f"track:{cand['id']}")
    assert "Now tracking" in out

    bill = await store.fetchone("SELECT * FROM finance_bills WHERE name = 'Netflix.Com'")
    assert bill is not None
    assert bill["amount"] == 15.49
    assert bill["frequency"] == "monthly"
    assert bill["due_date"] == cand["next_due"]
    assert bill["source"] == "discovered"
    assert bill["paid_this_cycle"] == 0

    updated = await store.fetchone(
        "SELECT status FROM finance_bill_candidates WHERE id = ?", (cand["id"],)
    )
    assert updated["status"] == "accepted"

    # Pressing the button again is a no-op with a clear reply.
    again = await handle_billmaster_callback(ctx, None, f"track:{cand['id']}")
    assert "already accepted" in again


async def test_dismiss_callback_never_resuggests(store, ctx):
    await seed_netflix(store)
    await job_bill_discovery(ctx)
    cand = await store.fetchone("SELECT * FROM finance_bill_candidates")

    out = await handle_billmaster_callback(ctx, None, f"dismiss:{cand['id']}")
    assert "won't be suggested again" in out
    updated = await store.fetchone(
        "SELECT status FROM finance_bill_candidates WHERE id = ?", (cand["id"],)
    )
    assert updated["status"] == "dismissed"

    # Discovery still sees the pattern, but the job stays silent forever.
    await job_bill_discovery(ctx)
    assert len(ctx.bot.approvals) == 1
    bills = await store.fetchall("SELECT * FROM finance_bills")
    assert bills == []


async def test_callback_garbage_payload(ctx):
    assert "made no sense" in await handle_billmaster_callback(ctx, None, "track:abc")
    assert "no longer exists" in await handle_billmaster_callback(ctx, None, "dismiss:999")


# -- infer_missing_due_dates -----------------------------------------------------


async def test_infer_missing_due_dates_from_history(store):
    await store.execute(
        "INSERT INTO finance_bills (name, amount, frequency, due_date) VALUES (?, ?, ?, NULL)",
        ("Acme Gym", 45.00, "monthly"),
    )
    # No transactions match this one — must stay NULL.
    await store.execute(
        "INSERT INTO finance_bills (name, amount, frequency, due_date) VALUES (?, ?, ?, NULL)",
        ("Mystery Cable", 80.00, "monthly"),
    )
    for n in (63, 33, 3):
        await add_txn(store, days_ago(n), "ACME GYM #101", 45.00)

    updated = await infer_missing_due_dates(store)
    assert updated == 1

    gym = await store.fetchone("SELECT due_date FROM finance_bills WHERE name = 'Acme Gym'")
    assert gym["due_date"] is not None
    due = datetime.date.fromisoformat(gym["due_date"])
    today = datetime.date.today()
    assert today <= due <= today + datetime.timedelta(days=40)

    cable = await store.fetchone("SELECT due_date FROM finance_bills WHERE name = 'Mystery Cable'")
    assert cable["due_date"] is None


# -- /bills_audit ----------------------------------------------------------------


async def test_bills_audit_renders_totals_and_flags(store, ctx):
    await store.execute(
        "INSERT INTO finance_bills (name, amount, due_date, frequency) VALUES (?, ?, ?, ?)",
        ("Rent", 1200.00, days_ahead(5), "monthly"),
    )
    await store.execute(
        "INSERT INTO finance_bills (name, amount, frequency, due_date) VALUES (?, ?, ?, NULL)",
        ("Water", 40.00, "monthly"),
    )
    await store.execute(
        "INSERT INTO finance_bill_candidates (merchant, amount, frequency, next_due) "
        "VALUES (?, ?, ?, ?)",
        ("SPOTIFY", 11.99, "monthly", days_ahead(9)),
    )
    await store.execute(
        "INSERT INTO finance_bill_candidates (merchant, amount, frequency, next_due, status) "
        "VALUES (?, ?, ?, ?, 'dismissed')",
        ("COFFEE CART", 4.50, "weekly", days_ahead(2)),
    )

    out = await handle_bills_audit(ctx, None, None)

    assert "Bill Audit" in out
    assert "Tracked bills (2)" in out
    assert "Rent" in out and "$1,200.00" in out and "in 5d" in out
    # Monthly obligation: 1200 + 40
    assert "Total monthly obligation: ~$1,240.00" in out
    # Missing due date flagged
    assert "no due date" in out
    assert "Missing due dates (1): Water" in out
    # Pending candidate listed, dismissed counted
    assert "Pending candidates (1)" in out
    assert "Spotify" in out and "$11.99" in out
    assert "Dismissed candidates: 1" in out


async def test_bills_audit_empty_state(ctx):
    out = await handle_bills_audit(ctx, None, None)
    assert "No bills tracked yet" in out
