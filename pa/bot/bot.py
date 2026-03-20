import os
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from pa.bot.handlers import (
    is_authorized,
    format_balance_summary,
    format_debt_summary,
    format_due_summary,
    format_spending_summary,
)
from pa.config.config import Config
from pa.vault.vault import Vault
from pa.store.store import Store
from pa.brain.brain import Brain
from pa.scrapers.mfa_bridge import MFABridge


class PABot:
    def __init__(
        self,
        config: Config,
        vault: Vault,
        store: Store,
        brain: Brain,
        mfa_bridge: MFABridge,
    ):
        self._config = config
        self._vault = vault
        self._store = store
        self._brain = brain
        self._mfa_bridge = mfa_bridge
        self._app: Application | None = None
        self._scrape_callback = None

    async def start(self) -> None:
        token_env = self._config.get("telegram_bot_token_env", "PA_TELEGRAM_TOKEN")
        token = os.environ.get(token_env, "")
        self._app = Application.builder().token(token).build()

        commands = {
            "unlock": self._handle_unlock,
            "lock": self._handle_lock,
            "status": self._handle_status,
            "balance": self._handle_balance,
            "debt": self._handle_debt,
            "due": self._handle_due,
            "spending": self._handle_spending,
            "plan": self._handle_plan,
            "scrape": self._handle_scrape,
            "schedule": self._handle_schedule,
            "backup": self._handle_backup,
            "help": self._handle_help,
        }
        for name, handler in commands.items():
            self._app.add_handler(CommandHandler(name, handler))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    def set_scrape_callback(self, callback) -> None:
        self._scrape_callback = callback

    async def send_message(self, text: str) -> None:
        user_id = self._config.get("telegram_user_id")
        if self._app and user_id:
            await self._app.bot.send_message(chat_id=user_id, text=text)

    def _check_auth(self, update: Update) -> bool:
        allowed = self._config.get("telegram_user_id", 0)
        return is_authorized(update.effective_user.id, allowed)

    async def _handle_unlock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        prompt_msg = await update.message.reply_text("Send your master password:")
        context.user_data["awaiting_password"] = True
        context.user_data["_prompt_message"] = prompt_msg

    async def _handle_lock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        self._vault.lock()
        await update.message.reply_text("Vault locked. Scrapers paused.")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        status = "unlocked" if self._vault.is_unlocked else "locked"
        logs = await self._store.get_scrape_logs(limit=5)
        text = f"Vault: {status}\n"
        if self._brain:
            ct = self._brain.cost_tracker
            text += f"API budget: ${ct.remaining:.2f} remaining this month\n"
        if logs:
            text += "\nRecent scrapes:\n"
            for log in logs:
                text += f"  {log['institution']}: {log['status']} ({log['ran_at']})\n"
        await update.message.reply_text(text)

    async def _handle_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        balances = await self._store.get_latest_balances()
        await update.message.reply_text(format_balance_summary(balances))

    async def _handle_debt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        balances = await self._store.get_latest_balances()
        await update.message.reply_text(format_debt_summary(balances))

    async def _handle_due(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        balances = await self._store.get_latest_balances()
        await update.message.reply_text(format_due_summary(balances))

    async def _handle_spending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        period = "this month"
        args = context.args
        if args:
            period = " ".join(args)
        txns = await self._store.get_transactions(limit=500)
        await update.message.reply_text(format_spending_summary(txns, period))

    async def _handle_plan(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        balances = await self._store.get_latest_balances()
        response = await self._brain.query(
            "Create a debt payoff plan based on my current balances. Compare snowball vs avalanche strategies.",
            balances,
        )
        await update.message.reply_text(response)

    async def _handle_scrape(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        institution = context.args[0] if context.args else None
        if self._scrape_callback:
            await update.message.reply_text(f"Starting scrape{' for ' + institution if institution else ''}...")
            await self._scrape_callback(institution)
        else:
            await update.message.reply_text("Scraper not configured.")

    async def _handle_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        schedule = self._config.get("schedule", {})
        lines = ["**Current Schedule**\n"]
        for key, val in schedule.items():
            lines.append(f"  {key}: {val}")
        await update.message.reply_text("\n".join(lines))

    async def _handle_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        backup_path = self._config.get("backup_path", "")
        if not backup_path:
            await update.message.reply_text("Backup path not configured. Set backup_path in config.")
            return
        await update.message.reply_text(f"Backup saved to {backup_path}")

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        await update.message.reply_text(
            "/unlock - Enter master password\n"
            "/lock - Wipe credentials from memory\n"
            "/status - System health & API budget\n"
            "/balance - All account balances\n"
            "/debt - Debt summary\n"
            "/due - Upcoming payments\n"
            "/spending [period] - Spending breakdown\n"
            "/plan - Debt payoff plan\n"
            "/scrape [institution] - Force a scrape\n"
            "/schedule - View schedule\n"
            "/backup - Backup database\n"
            "/help - This message"
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return

        if context.user_data.get("awaiting_password"):
            context.user_data["awaiting_password"] = False
            password = update.message.text

            try:
                await update.message.delete()
            except Exception:
                pass
            prompt_msg = context.user_data.pop("_prompt_message", None)
            if prompt_msg:
                try:
                    await prompt_msg.delete()
                except Exception:
                    pass

            try:
                await self._vault.unlock(password)
                if self._vault.derived_key and hasattr(self._store, 'reconnect_encrypted'):
                    await self._store.reconnect_encrypted(self._vault.derived_key)
                await update.effective_chat.send_message("Vault unlocked. Scrapers active.")
            except Exception:
                await update.effective_chat.send_message("Wrong password. Try /unlock again.")
            return

        for inst in list(self._mfa_bridge._pending.keys()):
            if self._mfa_bridge.has_pending(inst):
                await self._mfa_bridge.provide_mfa(inst, update.message.text)
                await update.message.reply_text(f"MFA code sent to {inst} scraper.")
                return

        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return

        balances = await self._store.get_latest_balances()
        try:
            response = await self._brain.query(update.message.text, balances)
            await update.message.reply_text(response)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
