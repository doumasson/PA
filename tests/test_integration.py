"""Integration smoke test — all modules wire together with plugin system."""
from pathlib import Path
import json
import pytest

from pa.core.config import Config
from pa.core.store import Store
from pa.core.brain import Brain
from pa.core.identity import NAME
from pa.vault.vault import Vault
from pa.scrapers.mfa_bridge import MFABridge
from pa.core.scheduler import PAScheduler
from pa.core.exceptions import VaultLockedError
from pa.plugins import discover_plugins
from pa.plugins.finance.repository import FinanceRepository


async def test_full_flow(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "telegram_user_id": 12345,
        "cost_cap_monthly_usd": 20.0,
    }))
    config = Config(config_path)
    await config.load()

    store = Store(tmp_path / "test.db")
    await store.connect()
    await store.init_schema()

    plugins = discover_plugins()
    assert any(p.name == "finance" for p in plugins)

    for p in plugins:
        ddl = p.schema_sql()
        if ddl:
            await store.init_plugin_schema(p.name, ddl)

    repo = FinanceRepository(store)
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_balance(acc_id, balance=1500.0)
    balances = await repo.get_latest_balances()
    assert len(balances) == 1

    brain = Brain(config=config)
    prompt = brain.build_system_prompt()
    assert NAME in prompt

    vault = Vault(tmp_path)
    await vault.init("test-password")
    await vault.add("wellsfargo", {"username": "test", "password": "pass"})
    creds = vault.get("wellsfargo")
    assert creds["username"] == "test"
    vault.lock()
    with pytest.raises(VaultLockedError):
        vault.get("wellsfargo")

    mfa = MFABridge(timeout_seconds=0.1)
    assert not mfa.has_pending("wellsfargo")

    scheduler = PAScheduler()
    for p in plugins:
        for job in p.jobs():
            scheduler.register_job(job)
    job_names = scheduler.get_job_names()
    assert "heartbeat" in job_names
    assert "bank_balance" in job_names

    await store.close()
