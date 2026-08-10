"""Kernel — boots and wires the v2 core, then runs until signalled.

Boot order: config+profile → store (data_dir configurable — SSD move is a
one-line config change) → learning/ledger/stats → brain → reflex → scheduler
→ bot → plugins (validated at the door) → vault auto-unlock → run.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from pathlib import Path

from pa.core.brain import Brain
from pa.core.config import Config
from pa.core.identity import GREETING, PERSONA
from pa.core.learning import LearningStore
from pa.core.ledger import Ledger
from pa.core.profile import Profile
from pa.core.reflex import Reflex
from pa.core.scheduler import PAScheduler
from pa.core.stats import Stats
from pa.core.store import Store
from pa.plugins import AppContext, discover_plugins
from pa.scrapers.mfa_bridge import MFABridge
from pa.vault.vault import Vault

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    base_dir = Path(__file__).parent.parent.parent
    config = Config(base_dir / "config.json")
    await config.load()

    data_dir = Path(config.get("data_dir") or base_dir / "data")
    data_dir.mkdir(parents=True, exist_ok=True)

    # httpx logs every Telegram long-poll and LLM call at INFO — a 24/7 log
    # flood that wears the SD card and buries real errors.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    profile = Profile.from_config(config.get("profile"))
    store = Store(data_dir / "pa.db")
    await store.connect()
    await store.init_schema()

    learning = LearningStore(store)
    ledger = Ledger(store, learning=learning)
    stats = Stats(store)
    brain = Brain(
        config.as_dict(), store=store, stats=stats, ledger=ledger, learning=learning
    )
    for module in (learning, ledger, stats, brain):
        await store.executescript(module.schema_sql())

    reflex = Reflex(learning, brain, stats=stats)
    scheduler = PAScheduler(ledger=ledger, timezone=profile.timezone)
    vault = Vault(data_dir)
    mfa_bridge = MFABridge()

    from pa.core.bot import PABot
    bot = PABot(
        config=config, vault=vault, store=store, brain=brain,
        reflex=reflex, mfa_bridge=mfa_bridge, profile=profile,
        ledger=ledger, stats=stats, learning=learning,
    )
    bot.set_scheduler(scheduler)
    ledger.set_notifier(bot.send_message)

    plugin_cfg = config.get("plugins") or {}
    plugins = discover_plugins(
        enabled=plugin_cfg.get("enabled"),
        ignore_broken=bool(plugin_cfg.get("ignore_broken", False)),
    )
    logger.info("Loaded plugins: %s", ", ".join(p.name for p in plugins) or "(none)")
    bot.set_plugin_names([p.name for p in plugins])

    fragments: list[str] = [PERSONA, profile.system_prompt_fragment()]
    for plugin in plugins:
        ddl = plugin.schema_sql()
        if ddl:
            await store.init_plugin_schema(plugin.name, ddl)
        for cmd in plugin.commands():
            bot.register_command(cmd)
        for nl in plugin.nl_handlers():
            bot.register_nl_handler(nl)
        for cb in plugin.callbacks():
            bot.register_callback(cb)
        for job in plugin.jobs():
            scheduler.register_job(job)
        fragment = plugin.system_prompt_fragment()
        if fragment:
            fragments.append(fragment)

    brain.set_base_system_prompt("\n\n".join(f for f in fragments if f))
    await brain.load_from_db()
    reflex.set_catalog(bot.intent_catalog())

    from pa.core.selfreport import weekly_self_report
    from pa.plugins import Job
    scheduler.register_job(Job(
        name="weekly_self_report", handler=weekly_self_report,
        trigger="cron", kwargs={"day_of_week": "sun", "hour": 19, "minute": 30},
    ))

    ctx = AppContext(
        store=store, vault=vault, brain=brain, bot=bot,
        scheduler=scheduler, config=config, profile=profile,
        learning=learning, ledger=ledger, stats=stats,
    )
    for plugin in plugins:
        await plugin.on_startup(ctx)

    vault_password = os.environ.get("PA_VAULT_PASSWORD", "")
    if vault_password:
        try:
            await vault.unlock(vault_password)
            if vault.derived_key and hasattr(store, "reconnect_encrypted"):
                await store.reconnect_encrypted(vault.derived_key)
        except Exception as e:
            await ledger.record(e, source="vault_auto_unlock")

    await bot.start()
    status = "All systems up." if vault.is_unlocked else "Vault locked — send /unlock."
    # A restart within the cooldown is maintenance, not news — stay quiet
    # unless the vault needs the user's attention.
    last_ping = await store.fetchone(
        "SELECT value FROM core_state WHERE key = 'last_startup_ping'"
    )
    recently_pinged = False
    if last_ping:
        try:
            recently_pinged = time.time() - float(last_ping["value"]) < 6 * 3600
        except ValueError:
            pass
    if not vault.is_unlocked or not recently_pinged:
        await bot.send_message(f"{GREETING} {status}")
        await store.execute(
            "INSERT INTO core_state (key, value) VALUES ('last_startup_ping', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(time.time()),),
        )

    scheduler.set_ctx(ctx)
    await scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        for plugin in plugins:
            try:
                await plugin.on_shutdown()
            except Exception as e:
                await ledger.record(e, source=f"shutdown:{plugin.name}")
        await scheduler.stop()
        await bot.stop()
        await store.close()
