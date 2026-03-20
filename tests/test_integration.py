"""Smoke test that all modules wire together correctly."""
from pathlib import Path

import pytest

from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge
from pa.scheduler.scheduler import PAScheduler
from pa.exceptions import VaultLockedError


async def test_full_flow_without_network(tmp_dir: Path, sample_config: Path):
    """Test the complete data flow: vault -> store -> brain query building."""
    # 1. Config
    config = Config(sample_config)
    await config.load()

    # 2. Vault
    vault = Vault(tmp_dir)
    await vault.init("test-password")
    await vault.add("wellsfargo", {"username": "testuser", "password": "testpass"})
    creds = vault.get("wellsfargo")
    assert creds["username"] == "testuser"

    # 3. Store
    store = Store(tmp_dir / "test.db")
    await store.connect()
    await store.init_schema()

    acc_id = await store.add_account("wellsfargo", "WF Checking", "checking")
    await store.add_balance(acc_id, balance=1500.00)

    cc_id = await store.add_account("synchrony", "Synchrony Card", "credit_card", interest_rate=0.2499, credit_limit=5000.0)
    await store.add_balance(cc_id, balance=2500.00, minimum_payment=35.00, due_date="2026-03-25")

    await store.add_transaction(acc_id, "2026-03-15", "GROCERY STORE", -85.00)

    # 4. Verify data retrieval
    balances = await store.get_latest_balances()
    assert len(balances) == 2

    txns = await store.get_transactions(account_id=acc_id)
    assert len(txns) == 1

    # 5. Brain builds system prompt with real data
    brain = Brain(config=config)
    prompt = brain.build_system_prompt(balances)
    assert "WF Checking" in prompt
    assert "Synchrony Card" in prompt

    # 6. MFA bridge works
    mfa = MFABridge(timeout_seconds=0.1)
    assert not mfa.has_pending("wellsfargo")

    # 7. Scheduler has jobs
    scheduler = PAScheduler()
    assert len(scheduler.get_job_names()) >= 5

    # 8. Vault lock works
    vault.lock()
    with pytest.raises(VaultLockedError):
        vault.get("wellsfargo")

    await store.close()
