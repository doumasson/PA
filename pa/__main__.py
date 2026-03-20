import asyncio
import signal
import sys
from pathlib import Path

from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge
from pa.scheduler.scheduler import PAScheduler
from pa.bot.bot import PABot


async def main() -> None:
    base_dir = Path(__file__).parent.parent
    config_path = base_dir / "config.json"
    data_dir = base_dir / "data"
    data_dir.mkdir(exist_ok=True)

    # Load config
    config = Config(config_path)
    await config.load()

    # Initialize modules
    vault = Vault(data_dir)
    mfa_bridge = MFABridge()
    brain = Brain(config=config)
    scheduler = PAScheduler()

    # Store starts unencrypted — will reconnect with encryption after vault unlock
    store = Store(data_dir / "pa.db")
    await store.connect()
    await store.init_schema()

    bot = PABot(
        config=config,
        vault=vault,
        store=store,
        brain=brain,
        mfa_bridge=mfa_bridge,
    )

    # Start bot
    await bot.start()

    # Detect first run vs returning user
    vault_exists = (data_dir / "vault.enc").exists()
    if vault_exists:
        await bot.send_message("PA restarted. Send /unlock to enter master password.")
    else:
        await bot.send_message(
            "Welcome to PA! First-time setup:\n"
            "1. Send /init to create your encrypted vault\n"
            "2. You'll set a master password\n"
            "3. Then add your financial institution credentials"
        )

    # Start scheduler
    async def scrape_handler(job_name: str) -> None:
        if not vault.is_unlocked:
            return
        pass

    async def alert_handler(job_name: str) -> None:
        if job_name == "heartbeat":
            await bot.send_message("PA running. All systems OK.")

    scheduler.register_scrape_handler(scrape_handler)
    scheduler.register_alert_handler(alert_handler)
    await scheduler.start()

    # Keep running until interrupted
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
        await scheduler.stop()
        await bot.stop()
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
