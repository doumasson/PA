"""Integration smoke test — v2 core wires together with the full plugin roster."""
from pathlib import Path
import json
import pytest

from pa.core.config import Config
from pa.core.store import Store
from pa.core.brain import Brain, Tier
from pa.core.learning import LearningStore
from pa.core.ledger import Ledger
from pa.core.stats import Stats
from pa.core.reflex import Reflex
from pa.core.profile import Profile
from pa.core.identity import PERSONA
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
        "llm": {
            "backends": {
                "fake": {
                    "base_url": "http://localhost:1/v1",
                    "trusted": True,
                    "models": {"parse": "m1", "reason": "m2"},
                }
            },
            "tiers": {"parse": ["fake"], "reason": ["fake"]},
        },
        "profile": {
            "owner": "Tester",
            "timezone": "UTC",
            "kids": [{"name": "Kid", "birth_date": "2015-01-01"}],
        },
    }))
    config = Config(config_path)
    await config.load()

    profile = Profile.from_config(config.get("profile"))
    assert profile.owner == "Tester"
    assert profile.kids[0].age() is not None

    store = Store(tmp_path / "test.db")
    await store.connect()
    await store.init_schema()

    learning = LearningStore(store)
    ledger = Ledger(store, learning=learning)
    stats = Stats(store)
    brain = Brain(config.as_dict(), store=store, stats=stats,
                  ledger=ledger, learning=learning)
    for module in (learning, ledger, stats, brain):
        await store.executescript(module.schema_sql())

    brain.set_base_system_prompt(
        "\n\n".join([PERSONA, profile.system_prompt_fragment()])
    )
    reflex = Reflex(learning, brain, stats=stats)

    # Every plugin discovers AND passes v2 contract validation
    plugins = discover_plugins()
    names = {p.name for p in plugins}
    assert {"finance", "google", "teller", "tasks", "health",
            "kids", "meals", "home", "research", "repair"} <= names

    for p in plugins:
        ddl = p.schema_sql()
        if ddl:
            await store.init_plugin_schema(p.name, ddl)

    # Reflex catalog builds from all NL handlers
    catalog = [
        {"intent_id": nl.intent_id, "description": nl.description,
         "examples": nl.examples}
        for p in plugins for nl in p.nl_handlers() if nl.intent_id
    ]
    reflex.set_catalog(catalog)
    assert any(c["intent_id"].startswith("finance.") for c in catalog)

    repo = FinanceRepository(store)
    acc_id = await repo.add_account("wellsfargo", "WF Checking", "checking")
    await repo.add_balance(acc_id, balance=1500.0)
    balances = await repo.get_latest_balances()
    assert len(balances) == 1

    # Learning round-trip through a plugin-style flow
    lid = await learning.remember(
        "plan", "spend amazon month",
        {"actions": [{"intent_id": "finance.spending"}], "synthesize": False},
        source="test",
    )
    hit = await learning.recall("plan", "spend amazon month")
    assert hit and hit["value"]["actions"][0]["intent_id"] == "finance.spending"
    await learning.confirm(lid)

    # Ledger records without raising
    sig = await ledger.record(RuntimeError("integration boom"), source="test")
    assert sig

    vault = Vault(tmp_path)
    await vault.init("test-password")
    await vault.add("wellsfargo", {"username": "test", "password": "pass"})
    assert vault.get("wellsfargo")["username"] == "test"
    assert vault.institutions() == ["wellsfargo"]
    vault.lock()
    with pytest.raises(VaultLockedError):
        vault.get("wellsfargo")

    mfa = MFABridge(timeout_seconds=0.1)
    assert not mfa.has_pending("wellsfargo")
    assert mfa.pending_institutions() == []

    scheduler = PAScheduler(ledger=ledger)
    for p in plugins:
        for job in p.jobs():
            scheduler.register_job(job)
    job_names = scheduler.get_job_names()
    assert "morning_sync" in job_names
    assert "gmail_check_morning" in job_names

    # Tier enum resolves models from config, not code
    assert Tier.PARSE.value == "parse" and Tier.REASON.value == "reason"

    await store.close()
