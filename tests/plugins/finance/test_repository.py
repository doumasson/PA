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


async def test_log_scrape(repo):
    await repo.log_scrape("wellsfargo", "success")
    logs = await repo.get_scrape_logs()
    assert len(logs) == 1
