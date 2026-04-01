"""Application entry point — discovers plugins, wires core modules, runs event loop."""
import asyncio
import signal
from pathlib import Path

from pa.core.config import Config
from pa.core.identity import NAME, GREETING
from pa.core.store import Store
from pa.core.brain import Brain
from pa.core.tier import TierClassifier
from pa.core.scheduler import PAScheduler
from pa.core.bot import PABot
from pa.vault.vault import Vault
from pa.scrapers.mfa_bridge import MFABridge
from pa.plugins import AppContext, discover_plugins


async def main() -> None:
    base_dir = Path(__file__).parent.parent.parent
    config_path = base_dir / "config.json"
    data_dir = base_dir / "data"
    data_dir.mkdir(exist_ok=True)

    config = Config(config_path)
    await config.load()

    vault = Vault(data_dir)
    mfa_bridge = MFABridge()
    brain = Brain(config=config)
    tier_classifier = TierClassifier()
    scheduler = PAScheduler()

    store = Store(data_dir / "pa.db")
    await store.connect()
    await store.init_schema()

    # Load persisted state into brain (conversation memory, cost tracker, preferences)
    await brain.load_from_db(store)

    bot = PABot(
        config=config, vault=vault, store=store,
        brain=brain, mfa_bridge=mfa_bridge,
    )

    bot.set_scheduler(scheduler)

    plugins = discover_plugins()
    plugin_names = [p.name for p in plugins]
    bot.set_plugin_names(plugin_names)

    for plugin in plugins:
        ddl = plugin.schema_sql()
        if ddl:
            await store.init_plugin_schema(plugin.name, ddl)
        for cmd in plugin.commands():
            bot.register_command(cmd)
        for nl in plugin.nl_handlers():
            bot.register_nl_handler(nl)
        for job in plugin.jobs():
            scheduler.register_job(job)
        patterns = plugin.tier_patterns()
        if patterns:
            tier_classifier.register(patterns)
        fragment = plugin.system_prompt_fragment()
        if fragment:
            brain._plugin_fragments.append(fragment)

    # Build intent catalog after all plugins have registered
    bot.build_intent_catalog()

    # Seed intent examples from keywords on first run
    count = await store.fetchone("SELECT COUNT(*) as c FROM core_intent_examples")
    if count and count['c'] == 0:
        for nl in bot._nl_handlers:
            if not nl.intent_id:
                continue
            for ex in nl.examples[:3]:
                await store.execute(
                    "INSERT INTO core_intent_examples (message, intent_id, source) VALUES (?, ?, 'seed')",
                    (ex, nl.intent_id)
                )
            for kw in nl.keywords[:3]:
                await store.execute(
                    "INSERT INTO core_intent_examples (message, intent_id, source) VALUES (?, ?, 'seed')",
                    (kw, nl.intent_id)
                )
        await brain.load_from_db(store)  # Reload with new examples

    ctx = AppContext(
        store=store, vault=vault, brain=brain,
        bot=bot, scheduler=scheduler, config=config,
    )
    for plugin in plugins:
        await plugin.on_startup(ctx)


    # Auto-unlock vault if password provided via environment
    import os
    vault_password = os.environ.get("PA_VAULT_PASSWORD", "")
    if vault_password:
        try:
            await vault.unlock(vault_password)
            if vault.derived_key and hasattr(store, 'reconnect_encrypted'):
                await store.reconnect_encrypted(vault.derived_key)
        except Exception as e:
            pass  # Will prompt via Telegram if auto-unlock fails

    await bot.start()

    if vault.is_unlocked:
        await bot.send_message(f"{GREETING} All systems up.")
    else:
        await bot.send_message(f"{GREETING} Vault locked — send /unlock to continue.")

    async def alert_handler(job_name: str) -> None:
        if job_name == "heartbeat":
            await bot.send_message(f"{NAME} running. All systems OK.")

    scheduler.set_ctx(ctx)
    scheduler.register_alert_handler(alert_handler)
    await scheduler.start()

    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for plugin in plugins:
            await plugin.on_shutdown()
        await scheduler.stop()
        await bot.stop()
        await store.close()
