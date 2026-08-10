# tests/plugins/finance/test_repository.py
from pathlib import Path
import pytest
from pa.core.store import Store
from pa.plugins.finance.repository import FinanceRepository


@pytest.fixture
async def repo(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    await store.connect()
    await store.init_schema()
    schema_path = Path(__file__).parent.parent.parent.parent / "pa" / "plugins" / "finance" / "schema.sql"
    ddl = schema_path.read_text(encoding="utf-8")
    await store.init_plugin_schema("finance", ddl)
    r = FinanceRepository(store)
    yield r
    await store.close()


async def test_add_and_get_account(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    assert acc_id > 0
    accounts = await repo.get_accounts()
    assert len(accounts) == 1
    assert accounts[0]["institution"] == "wellsfargo"


async def test_add_and_get_balance(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_balance(acc_id, balance=1500.0)
    balances = await repo.get_latest_balances()
    assert len(balances) == 1
    assert balances[0]["balance"] == 1500.0


async def test_add_transaction_dedup(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    inserted = await repo.add_transaction(acc_id, "2026-03-15", "GROCERY", -85.0)
    assert inserted
    dup = await repo.add_transaction(acc_id, "2026-03-15", "GROCERY", -85.0)
    assert not dup


async def test_get_transactions(repo):
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_transaction(acc_id, "2026-03-15", "GROCERY", -85.0)
    txns = await repo.get_transactions(account_id=acc_id)
    assert len(txns) == 1


async def test_pending_to_posted_updates_in_place(repo):
    """Teller re-dates a transaction when it settles; the posted version must
    update the pending row, not land as a second transaction."""
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    inserted = await repo.add_transaction(
        acc_id, "2026-07-02", "PURCHASE GRUBHUB CHIL NEW YORK NY CARD 1234",
        49.12, is_pending=True, teller_id="txn_abc123",
    )
    assert inserted
    again = await repo.add_transaction(
        acc_id, "2026-07-03", "PURCHASE GRUBHUB CHIL NEW YORK NY CARD 1234",
        49.12, posted_date="2026-07-03", is_pending=False, teller_id="txn_abc123",
    )
    assert not again
    txns = await repo.get_transactions(account_id=acc_id)
    assert len(txns) == 1
    assert txns[0]["date"] == "2026-07-03"
    assert not txns[0]["is_pending"]


async def test_teller_txn_adopts_legacy_row(repo):
    """Rows synced before teller_id existed get claimed by the matching
    Teller transaction instead of duplicated."""
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_transaction(acc_id, "2026-07-02", "PURCHASE PRIME VIDEO - - WA CARD 9", 26.99)
    again = await repo.add_transaction(
        acc_id, "2026-07-03", "PURCHASE PRIME VIDEO - - WA CARD 9",
        26.99, is_pending=False, teller_id="txn_prime1",
    )
    assert not again
    txns = await repo.get_transactions(account_id=acc_id)
    assert len(txns) == 1
    assert txns[0]["teller_id"] == "txn_prime1"
    assert txns[0]["date"] == "2026-07-03"


async def test_distinct_teller_ids_are_distinct_transactions(repo):
    """Two genuinely separate charges — same merchant, amount, and day —
    must both survive when Teller gives them different ids."""
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    a = await repo.add_transaction(acc_id, "2026-07-03", "MCDONALDS 5", 6.92, teller_id="txn_1")
    b = await repo.add_transaction(acc_id, "2026-07-03", "MCDONALDS 5", 6.92, teller_id="txn_2")
    assert a and b
    txns = await repo.get_transactions(account_id=acc_id)
    assert len(txns) == 2


async def test_resync_repairs_amount_sign(repo):
    """Rows stored before Teller's sign convention was honored (deposits
    saved positive) get their amount corrected on the next sync."""
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_transaction(
        acc_id, "2026-06-12", "STOLLE MACHINERY PAYROLL", 3889.22, teller_id="txn_pay1"
    )
    again = await repo.add_transaction(
        acc_id, "2026-06-12", "STOLLE MACHINERY PAYROLL", -3889.22, teller_id="txn_pay1"
    )
    assert not again
    txns = await repo.get_transactions(account_id=acc_id)
    assert len(txns) == 1
    assert txns[0]["amount"] == -3889.22


async def test_adoption_matches_legacy_row_with_flipped_sign(repo):
    """A legacy row saved with the wrong sign is still recognized as the
    same transaction and repaired, not duplicated."""
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_transaction(acc_id, "2026-06-12", "STOLLE MACHINERY PAYROLL", 3889.22)
    again = await repo.add_transaction(
        acc_id, "2026-06-12", "STOLLE MACHINERY PAYROLL", -3889.22, teller_id="txn_pay1"
    )
    assert not again
    txns = await repo.get_transactions(account_id=acc_id)
    assert len(txns) == 1
    assert txns[0]["amount"] == -3889.22
    assert txns[0]["teller_id"] == "txn_pay1"


async def test_log_scrape(repo):
    await repo.log_scrape("wellsfargo", "success")
    logs = await repo.get_scrape_logs()
    assert len(logs) == 1
