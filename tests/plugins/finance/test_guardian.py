# tests/plugins/finance/test_guardian.py
"""Money Guardian anomaly detection — real tmp SQLite Store, no LLM, no network."""
import datetime
import hashlib
import types
from pathlib import Path

import pytest

from pa.core.store import Store
from pa.plugins.finance.commands import handle_guardian
from pa.plugins.finance.guardian import (
    find_duplicate_charges,
    find_new_merchants,
    find_price_hikes,
    job_guardian_check,
    normalize_merchant,
)

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "pa" / "plugins" / "finance" / "schema.sql"
)


def days_ago(n: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


class FakeBot:
    def __init__(self):
        self.messages: list[str] = []

    async def send_message(self, text: str) -> None:
        self.messages.append(text)


@pytest.fixture
async def store(tmp_path: Path):
    s = Store(tmp_path / "test.db")
    await s.connect()
    await s.init_schema()
    await s.init_plugin_schema("finance", _SCHEMA_PATH.read_text(encoding="utf-8"))
    # Transactions reference finance_accounts (FKs are ON in Store).
    await s.execute(
        "INSERT INTO finance_accounts (institution, name, type) VALUES (?, ?, ?)",
        ("test", "Test Checking", "checking"),
    )
    yield s
    await s.close()


@pytest.fixture
def ctx(store):
    return types.SimpleNamespace(store=store, bot=FakeBot())


async def add_txn(store, date: str, description: str, amount: float,
                  is_pending: bool = False, salt: str = "") -> None:
    """Insert a transaction with a unique dedup_hash (salt forces distinct
    hashes for otherwise-identical rows, like real double-billing)."""
    dedup = hashlib.sha256(f"1|{date}|{description}|{amount}|{salt}".encode()).hexdigest()
    await store.execute(
        "INSERT INTO finance_transactions "
        "(account_id, date, description, amount, dedup_hash, is_pending) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, date, description, amount, dedup, is_pending),
    )


# -- normalize_merchant --------------------------------------------------------


def test_normalize_merchant():
    assert normalize_merchant("Surfshark*8842 NL") == "SURFSHARK NL"
    assert normalize_merchant("WALMART #1234") == "WALMART"
    assert normalize_merchant("  netflix.com   9915  ") == "NETFLIX.COM"
    # Same merchant, different store numbers → same key
    assert normalize_merchant("SHELL OIL 5744") == normalize_merchant("SHELL OIL 9021")


# -- duplicate charges ---------------------------------------------------------


async def test_duplicate_charge_detected(store):
    await add_txn(store, days_ago(5), "ACME GYM #101", 45.00)
    await add_txn(store, days_ago(3), "ACME GYM #102", 45.00)  # 2 days later, same amount

    findings = await find_duplicate_charges(store)
    assert len(findings) == 1
    f = findings[0]
    assert f["kind"] == "duplicate"
    assert f["merchant"] == "ACME GYM"
    assert f["amount"] == 45.00
    assert "Possible duplicate" in f["message"]
    assert "$45.00" in f["message"]


async def test_different_amounts_not_duplicates(store):
    # Legit repeat visits: same merchant, different amounts
    await add_txn(store, days_ago(4), "SHELL OIL 5744", 30.00)
    await add_txn(store, days_ago(2), "SHELL OIL 5744", 45.00)
    assert await find_duplicate_charges(store) == []


async def test_duplicate_ignores_pending_small_and_far_apart(store):
    # Pending twin is excluded
    await add_txn(store, days_ago(6), "STREAMCO", 20.00)
    await add_txn(store, days_ago(5), "STREAMCO", 20.00, is_pending=True)
    # Under the $5 floor
    await add_txn(store, days_ago(3), "COFFEE CART", 3.50)
    await add_txn(store, days_ago(2), "COFFEE CART", 3.50)
    # Same amount but 10 days apart — outside the 4-day window
    await add_txn(store, days_ago(12), "GROCER", 60.00)
    await add_txn(store, days_ago(2), "GROCER", 60.00)
    assert await find_duplicate_charges(store) == []


# -- price hikes ---------------------------------------------------------------


async def test_price_hike_detected(store):
    # Monthly subscription creeping 9.99 → 9.99 → 12.99
    await add_txn(store, days_ago(60), "SURFSHARK*1001", 9.99)
    await add_txn(store, days_ago(30), "SURFSHARK*1002", 9.99)
    await add_txn(store, days_ago(0), "SURFSHARK*1003", 12.99)

    findings = await find_price_hikes(store)
    assert len(findings) == 1
    f = findings[0]
    assert f["kind"] == "hike"
    assert f["merchant"] == "SURFSHARK"
    assert f["old_amount"] == 9.99
    assert f["new_amount"] == 12.99
    assert "Subscription creep" in f["message"]
    assert "+30%" in f["message"]


async def test_non_monthly_merchant_not_flagged(store):
    # Weekly cadence (avg gap 7 days) — big jump but not subscription-shaped
    await add_txn(store, days_ago(14), "LUNCH SPOT", 9.99)
    await add_txn(store, days_ago(7), "LUNCH SPOT", 9.99)
    await add_txn(store, days_ago(0), "LUNCH SPOT", 19.99)
    assert await find_price_hikes(store) == []


async def test_small_increase_not_flagged(store):
    # +$0.50 on $9.99 is under max($2, 5%) → no alert
    await add_txn(store, days_ago(60), "STREAMCO", 9.99)
    await add_txn(store, days_ago(30), "STREAMCO", 9.99)
    await add_txn(store, days_ago(0), "STREAMCO", 10.49)
    assert await find_price_hikes(store) == []


# -- new merchants -------------------------------------------------------------


async def test_new_merchant_over_threshold_flagged(store):
    await add_txn(store, days_ago(1), "FANCY ELECTRONICS", 250.00)
    findings = await find_new_merchants(store)
    assert len(findings) == 1
    f = findings[0]
    assert f["kind"] == "new_merchant"
    assert f["merchant"] == "FANCY ELECTRONICS"
    assert f["amount"] == 250.00
    assert "New merchant" in f["message"]
    assert days_ago(1) in f["message"]


async def test_new_merchant_under_threshold_ignored(store):
    await add_txn(store, days_ago(1), "SMALL SHOP", 40.00)  # under $75
    assert await find_new_merchants(store) == []


async def test_known_merchant_not_flagged_as_new(store):
    # First seen 60 days ago — a big recent charge is not "new merchant"
    await add_txn(store, days_ago(60), "OLD GROCER 12", 22.00)
    await add_txn(store, days_ago(1), "OLD GROCER 12", 120.00)
    assert await find_new_merchants(store) == []


# -- job: alerting + fingerprint dedup -----------------------------------------


async def test_job_sends_once_then_stays_silent(store, ctx):
    # True duplicate: 2x $45 two days apart
    await add_txn(store, days_ago(5), "ACME GYM #101", 45.00)
    await add_txn(store, days_ago(3), "ACME GYM #102", 45.00)

    await job_guardian_check(ctx)
    assert len(ctx.bot.messages) == 1
    msg = ctx.bot.messages[0]
    assert msg.startswith("\U0001f6e1 Money Guardian:")
    assert "Possible duplicate" in msg
    assert "ACME GYM" in msg

    # Second run: same findings, fingerprints already recorded → no message
    await job_guardian_check(ctx)
    assert len(ctx.bot.messages) == 1

    # Alert row persisted exactly once
    rows = await store.fetchall("SELECT * FROM finance_guardian_alerts")
    assert len(rows) == 1
    assert rows[0]["kind"] == "duplicate"


async def test_job_silent_when_no_findings(store, ctx):
    await add_txn(store, days_ago(2), "NORMAL SHOP", 12.00)
    await job_guardian_check(ctx)
    assert ctx.bot.messages == []


async def test_job_combines_multiple_findings_in_one_message(store, ctx):
    await add_txn(store, days_ago(5), "ACME GYM #101", 45.00)
    await add_txn(store, days_ago(3), "ACME GYM #102", 45.00)
    await add_txn(store, days_ago(1), "FANCY ELECTRONICS", 250.00)

    await job_guardian_check(ctx)
    assert len(ctx.bot.messages) == 1
    msg = ctx.bot.messages[0]
    assert "Possible duplicate" in msg
    assert "New merchant" in msg


# -- /guardian command ---------------------------------------------------------


async def test_guardian_command_reports_and_marks_alerted(store, ctx):
    await add_txn(store, days_ago(5), "ACME GYM #101", 45.00)
    await add_txn(store, days_ago(3), "ACME GYM #102", 45.00)

    # Before any job run: finding shown, not marked
    out = await handle_guardian(ctx, None, None)
    assert "Possible duplicate" in out
    assert "(already alerted)" not in out

    # After the job alerts, /guardian still shows it — marked
    await job_guardian_check(ctx)
    out = await handle_guardian(ctx, None, None)
    assert "Possible duplicate" in out
    assert "(already alerted)" in out


async def test_guardian_command_all_clear(store, ctx):
    out = await handle_guardian(ctx, None, None)
    assert "all clear" in out
