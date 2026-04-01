import json
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

from pa.core.identity import NAME
from pa.plugins import Command, AppContext


class PABot:
    _builtin_commands = {"unlock", "lock", "status", "help", "plugins", "addcred", "creds", "delcred", "prefs"}

    def __init__(self, config: Any, vault: Any, store: Any, brain: Any, mfa_bridge: Any):
        self._config = config
        self._vault = vault
        self._store = store
        self._brain = brain
        self._mfa_bridge = mfa_bridge
        self._app: Application | None = None
        self._command_registry: dict[str, Command] = {}
        self._nl_handlers: list = []
        self._intent_registry: dict[str, Any] = {}  # intent_id -> NLHandler
        self._intent_catalog: list[dict] = []  # built after all plugins register
        self._plugin_names: list[str] = []
        self._scheduler = None

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def register_command(self, cmd: Command) -> None:
        if cmd.name in self._builtin_commands:
            raise ValueError(f"Cannot override builtin command: /{cmd.name}")
        self._command_registry[cmd.name] = cmd

    def register_nl_handler(self, handler) -> None:
        self._nl_handlers.append(handler)
        if handler.intent_id:
            self._intent_registry[handler.intent_id] = handler

    def build_intent_catalog(self) -> None:
        """Build the intent catalog from registered handlers. Call after all plugins register."""
        self._intent_catalog = []
        for intent_id, handler in self._intent_registry.items():
            self._intent_catalog.append({
                "intent_id": intent_id,
                "description": handler.description,
                "examples": handler.examples,
            })

    def set_plugin_names(self, names: list[str]) -> None:
        self._plugin_names = names

    def build_help_text(self) -> str:
        lines = [
            f"**{NAME} Commands**\n",
            "/unlock - Enter master password",
            "/lock - Lock vault",
            "/addcred - Add institution credentials",
            "/creds - List stored credentials",
            "/delcred - Remove credentials",
            "/status - System status",
            "/prefs - View/clear learned preferences",
            "/plugins - Active plugins",
        ]
        for name, cmd in sorted(self._command_registry.items()):
            lines.append(f"/{name} - {cmd.description}")
        lines.append("/help - This message")
        return "\n".join(lines)

    async def start(self) -> None:
        token_env = self._config.get("telegram_bot_token_env", "PA_TELEGRAM_TOKEN")
        token = os.environ.get(token_env, "")
        self._app = Application.builder().token(token).build()

        builtins = {
            "unlock": self._handle_unlock,
            "lock": self._handle_lock,
            "addcred": self._handle_addcred,
            "creds": self._handle_creds,
            "delcred": self._handle_delcred,
            "status": self._handle_status,
            "prefs": self._handle_prefs,
            "help": self._handle_help,
            "plugins": self._handle_plugins,
        }
        for name, handler in builtins.items():
            self._app.add_handler(CommandHandler(name, handler))

        for cmd_name, cmd in self._command_registry.items():
            async def make_handler(c=cmd):
                async def h(update: Update, context: ContextTypes.DEFAULT_TYPE):
                    if not self._check_auth(update):
                        return
                    ctx = AppContext(
                        store=self._store, vault=self._vault, brain=self._brain,
                        bot=self, scheduler=None, config=self._config,
                    )
                    result = await c.handler(ctx, update, context)
                    if result:
                        await update.message.reply_text(result)
                return h
            self._app.add_handler(CommandHandler(cmd_name, await make_handler()))

        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        from pa.plugins.agent.voice import handle_voice
        self._app.add_handler(
            MessageHandler(
                filters.VOICE,
                lambda u, c: handle_voice(u, c, self._brain, self)
            )
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send_message(self, text: str) -> None:
        user_id = self._config.get("telegram_user_id")
        if self._app and user_id:
            # Split long messages for Telegram's 4096 char limit
            while text:
                chunk = text[:4000]
                if len(text) > 4000:
                    split_at = chunk.rfind('\n')
                    if split_at > 0:
                        chunk = text[:split_at]
                    text = text[len(chunk):].lstrip('\n')
                else:
                    text = ""
                await self._app.bot.send_message(chat_id=user_id, text=chunk)

    def _check_auth(self, update: Update) -> bool:
        allowed = self._config.get("telegram_user_id", 0)
        return update.effective_user.id == allowed

    async def _handle_unlock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        old_prompt = context.user_data.pop("_prompt_message", None)
        if old_prompt:
            try:
                await old_prompt.delete()
            except Exception:
                pass
        prompt_msg = await update.message.reply_text("Send your master password:")
        context.user_data["awaiting_password"] = True
        context.user_data["_prompt_message"] = prompt_msg

    async def _handle_lock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        self._vault.lock()
        await update.message.reply_text("Vault locked.")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        status = "unlocked" if self._vault.is_unlocked else "locked"
        text = f"Vault: {status}\n"
        text += "Mode: Subscription (CLIProxyAPI)\n"
        text += f"Plugins: {', '.join(self._plugin_names) or 'none'}"
        await update.message.reply_text(text)

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        await update.message.reply_text(self.build_help_text())

    async def _handle_plugins(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if self._plugin_names:
            text = "Active plugins:\n" + "\n".join(f"  - {n}" for n in self._plugin_names)
        else:
            text = "No plugins loaded."
        await update.message.reply_text(text)

    async def _handle_prefs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        arg = context.args[0].lower() if context.args else None
        if arg == "clear":
            if self._store:
                await self._store.execute("DELETE FROM core_preferences")
            self._brain._preferences.clear()
            await update.message.reply_text("All preferences cleared.")
            return
        prefs = self._brain._preferences
        if not prefs:
            await update.message.reply_text("No preferences learned yet. Just tell me what you like or don't like!")
            return
        lines = [f"**Learned Preferences** ({len(prefs)} total)\n"]
        for i, p in enumerate(prefs[-15:], 1):
            lines.append(f"{i}. {p}")
        lines.append("\nUse /prefs clear to reset.")
        await update.message.reply_text("\n".join(lines))

    async def _handle_addcred(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return

        institution = " ".join(context.args) if context.args else None
        if institution:
            context.user_data["addcred"] = {"institution": institution, "step": "url"}
            prompt = await update.message.reply_text(f"Login page URL for {institution}:")
            context.user_data["_addcred_prompt"] = prompt
        else:
            context.user_data["addcred"] = {"step": "institution"}
            prompt = await update.message.reply_text("Institution name (e.g. wellsfargo, synchrony):")
            context.user_data["_addcred_prompt"] = prompt

    async def _handle_creds(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        creds = {k: v for k, v in self._vault._data.items() if not k.startswith("_")}
        if not creds:
            await update.message.reply_text("No credentials stored. Use /addcred to add some.")
            return
        lines = ["Stored credentials:\n"]
        for inst, data in sorted(creds.items()):
            username = data.get("username", "?")
            url = data.get("url", "")
            if len(username) > 4:
                masked = username[:2] + "*" * (len(username) - 4) + username[-2:]
            else:
                masked = "****"
            url_short = url.split("//")[-1][:30] if url else "no URL"
            lines.append(f"  {inst}: {masked} ({url_short})")
        await update.message.reply_text("\n".join(lines))

    async def _handle_delcred(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /delcred <institution>")
            return
        institution = " ".join(context.args)
        if institution not in self._vault._data:
            await update.message.reply_text(f"No credentials found for '{institution}'.")
            return
        del self._vault._data[institution]
        await self._vault._save()
        await update.message.reply_text(f"Credentials for '{institution}' removed.")

    async def _delete_msg(self, msg: Any) -> None:
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._check_auth(update):
            return

        if context.user_data.get("awaiting_password"):
            context.user_data["awaiting_password"] = False
            password = update.message.text
            await self._delete_msg(update.message)
            await self._delete_msg(context.user_data.pop("_prompt_message", None))
            try:
                was_new = not self._vault._params_path.exists()
                await self._vault.unlock(password)
                if self._vault.derived_key and hasattr(self._store, 'reconnect_encrypted'):
                    await self._store.reconnect_encrypted(self._vault.derived_key)
                if was_new:
                    await update.effective_chat.send_message(
                        "Vault created and unlocked. Remember this password!"
                    )
                else:
                    await update.effective_chat.send_message("Vault unlocked.")
            except Exception:
                await update.effective_chat.send_message("Wrong password. Try /unlock again.")
            return

        addcred = context.user_data.get("addcred")
        if addcred:
            step = addcred["step"]
            text = update.message.text.strip()
            await self._delete_msg(context.user_data.pop("_addcred_prompt", None))

            if step == "institution":
                addcred["institution"] = text
                addcred["step"] = "url"
                await self._delete_msg(update.message)
                prompt = await update.effective_chat.send_message(f"Login page URL for {text}:")
                context.user_data["_addcred_prompt"] = prompt
            elif step == "url":
                addcred["url"] = text
                addcred["step"] = "username"
                await self._delete_msg(update.message)
                prompt = await update.effective_chat.send_message(f"Username for {addcred['institution']}:")
                context.user_data["_addcred_prompt"] = prompt
            elif step == "username":
                addcred["username"] = text
                addcred["step"] = "password"
                await self._delete_msg(update.message)
                prompt = await update.effective_chat.send_message(
                    f"Password for {addcred['institution']}:"
                )
                context.user_data["_addcred_prompt"] = prompt
            elif step == "password":
                await self._delete_msg(update.message)
                institution = addcred["institution"]
                username = addcred["username"]
                url = addcred.get("url", "")
                del context.user_data["addcred"]
                try:
                    await self._vault.add(institution, {
                        "url": url,
                        "username": username,
                        "password": text,
                    })
                    await update.effective_chat.send_message(
                        f"Credentials saved for {institution}."
                    )
                except Exception as e:
                    await update.effective_chat.send_message(f"Error saving: {e}")
            return

        if hasattr(self, '_mfa_subprocess') and self._mfa_subprocess:
            proc = self._mfa_subprocess
            code = update.message.text.strip()
            try:
                mfa_msg = json.dumps({"event": "mfa_code", "code": code})
                proc.stdin.write(mfa_msg.encode() + b"\n")
                await proc.stdin.drain()
                await update.message.reply_text("MFA code sent. Continuing scrape...")
            except Exception as e:
                await update.message.reply_text(f"Failed to relay MFA code: {e}")
            finally:
                self._mfa_subprocess = None
                if hasattr(self, '_mfa_institution'):
                    self._mfa_institution = None
            return

        for inst in list(self._mfa_bridge._pending.keys()):
            if self._mfa_bridge.has_pending(inst):
                await self._mfa_bridge.provide_mfa(inst, update.message.text)
                await update.message.reply_text(f"MFA code sent to {inst}.")
                return
            return

        text = update.message.text
        await self._route_message(text, update, context)

    async def _route_message(self, text: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Route a text message through AI intent classification and handlers."""
        ctx = AppContext(
            store=self._store, vault=self._vault, brain=self._brain,
            bot=self, scheduler=self._scheduler, config=self._config,
        )

        # AI-powered intent classification
        if self._intent_catalog:
            try:
                intents = await self._brain.classify_intent(
                    user_message=text,
                    handler_catalog=self._intent_catalog,
                    recent_context=self._brain._conversation[-6:],
                )
                if intents:
                    results = []
                    prior_result = None
                    for intent in intents:
                        handler = self._intent_registry.get(intent.get("intent_id", ""))
                        if handler:
                            try:
                                # Pass prior handler result as context for chaining
                                if prior_result:
                                    chained_text = f"{text}\n\n[Prior result: {prior_result}]"
                                else:
                                    chained_text = text
                                result = await handler.handler(ctx, chained_text, update)
                                if result:
                                    results.append(result)
                                    prior_result = result
                                    # Learn from successful route
                                    if len(self._brain._intent_examples) < 200:
                                        await self._brain.confirm_intent(text, intent["intent_id"])
                            except Exception as e:
                                results.append(f"Error: {e}")
                    if results:
                        combined = "\n\n".join(results)
                        await self._send_long(update, combined)
                        # Remember the exchange in conversation memory
                        await self._brain.remember_message("user", text)
                        await self._brain.remember_message("assistant", combined)
                        return
            except Exception:
                pass  # Fall through to general conversation on classifier failure

        # Fallback: general conversation through brain
        try:
            response = await self._brain.query(text)
            await self._send_long(update, response)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    @staticmethod
    async def _send_long(update: Update, text: str, chunk_size: int = 4000) -> None:
        """Send long messages split into Telegram-safe chunks."""
        if len(text) <= chunk_size:
            await update.message.reply_text(text)
            return
        # Split on newlines near the limit
        while text:
            if len(text) <= chunk_size:
                await update.message.reply_text(text)
                break
            split_at = text.rfind('\n', 0, chunk_size)
            if split_at == -1:
                split_at = chunk_size
            await update.message.reply_text(text[:split_at])
            text = text[split_at:].lstrip('\n')
