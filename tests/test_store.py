import pytest
from pathlib import Path

from pa.store.store import Store


@pytest.fixture
async def store(tmp_dir: Path):
    s = Store(tmp_dir / "test.db")
    await s.connect()
    await s.init_schema()
    yield s
    await s.close()


async def test_connect_and_init_schema(store: Store):
    assert store is not None


async def test_add_account(store: Store):
    account_id = await store.add_account(
        institution="wellsfargo",
        name="WF Checking",
        account_type="checking",
    )
    assert account_id == 1


async def test_get_accounts(store: Store):
    await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_account("synchrony", "Synchrony Card", "credit_card", interest_rate=0.2499, credit_limit=5000.0)
    accounts = await store.get_accounts()
    assert len(accounts) == 2
    assert accounts[1]["interest_rate"] == 0.2499


async def test_add_balance(store: Store):
    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_balance(
        account_id=acc_id,
        balance=1500.00,
    )
    balances = await store.get_latest_balances()
    assert len(balances) == 1
    assert balances[0]["balance"] == 1500.00


async def test_add_transaction_dedup(store: Store):
    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    txn = {
        "account_id": acc_id,
        "date": "2026-03-15",
        "description": "AMAZON PURCHASE",
        "amount": 49.99,
    }
    inserted = await store.add_transaction(**txn)
    assert inserted is True
    inserted2 = await store.add_transaction(**txn)
    assert inserted2 is False


async def test_get_transactions_by_account(store: Store):
    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_transaction(acc_id, "2026-03-10", "GROCERY STORE", -85.00)
    await store.add_transaction(acc_id, "2026-03-12", "GAS STATION", -45.00)
    txns = await store.get_transactions(account_id=acc_id)
    assert len(txns) == 2


async def test_log_scrape(store: Store):
    await store.log_scrape(
        institution="wellsfargo",
        status="success",
        duration_seconds=12.5,
    )
    logs = await store.get_scrape_logs(limit=1)
    assert logs[0]["status"] == "success"
