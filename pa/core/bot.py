"""Telegram bot v2 — thin interface over the reflex ladder.

Message flow: auth → secret-entry flows (password/creds/MFA) → preference
detection → reflex.route() (L0 learned / L1 planned) → execute actions,
chaining results → REASON-tier chat fallback. Every outcome feeds back into
the learning store via reflex.record_outcome().
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from pa.core.brain import Tier
from pa.core.exceptions import BrainAPIError
from pa.core.identity import NAME
from pa.plugins import AppContext, Command

logger = logging.getLogger(__name__)

# Substrings that mean "the LLM backend has no valid credentials" rather than
# "the LLM had a bad day". Matched against the text of a BrainAPIError, which
# wraps whatever the proxy returned.
_AUTH_FAILURE_MARKERS = (
    "auth_unavailable",
    "no auth available",
    "authentication_error",
    "has been revoked",
    "invalid_api_key",
    "401",
)

_BRAIN_DOWN_MSG = (
    "🧠 <b>My language backend is unauthenticated</b> — I can't think right now.\n\n"
    "This is not a bug in me; the CLIProxyAPI OAuth token was revoked. "
    "Everything that needs reasoning (planning, Bart, bill detection) will keep "
    "failing until it's renewed. On the Pi:\n"
    "<pre>cli-proxy-api -claude-login -no-browser \\\n"
    "  -config /etc/cliproxy/config.yaml</pre>\n"
    "then <code>sudo systemctl restart pa.service</code>.\n\n"
    "Commands that don't need reasoning still work: /bags /check /status /errors /stats."
)

_BRAIN_FLAKY_MSG = (
    "🧠 My language backend didn't answer (it's reachable but erroring). "
    "Nothing is lost — try again in a moment. Details are in /errors."
)


def brain_failure_message(exc: BaseException) -> str | None:
    """Human-readable text for an LLM failure, or None if `exc` isn't one.

    WHY: the handlers used to reply with the raw exception — the user saw
    `/foo failed: All backends failed for tier 'reason': Error code: 500 -
    {'error': {'message': 'auth_unavailable...` on every single message. That is
    noise that tells him nothing he can act on. An unauthenticated backend is a
    ONE-LINE FIX, so say the fix.

    The distinction matters: a revoked token will fail forever and "try again"
    is a lie, whereas a transient backend error genuinely is worth retrying.
    """
    if not isinstance(exc, BrainAPIError):
        return None
    blob = str(exc).lower()
    if any(m in blob for m in _AUTH_FAILURE_MARKERS):
        return _BRAIN_DOWN_MSG
    return _BRAIN_FLAKY_MSG

# Durable-preference wording only. Broad phrases ("i want", "i like",
# "make sure") turned everyday requests into permanent system-prompt lines.
_PREFERENCE_PHRASES = (
    "i prefer", "from now on", "always send", "never send",
    "stop sending", "don't send", "dont send",
    "remember that", "keep in mind",
)


class PABot:
    _builtin_commands = {
        "unlock", "lock", "status", "help", "plugins", "addcred", "creds",
        "delcred", "prefs", "stats", "errors",
    }

    def __init__(
        self, config: Any, vault: Any, store: Any, brain: Any, reflex: Any,
        mfa_bridge: Any, profile: Any = None, ledger: Any = None,
        stats: Any = None, learning: Any = None,
    ):
        self._config = config
        self._vault = vault
        self._store = store
        self._brain = brain
        self._reflex = reflex
        self._mfa_bridge = mfa_bridge
        self._profile = profile
        self._ledger = ledger
        self._stats = stats
        self._learning = learning
        self._app: Application | None = None
        self._command_registry: dict[str, Command] = {}
        self._nl_handlers: list = []
        self._intent_registry: dict[str, Any] = {}
        self._callback_registry: dict[str, Any] = {}
        self._plugin_names: list[str] = []
        self._scheduler = None
        self._mfa_subprocess = None  # set by scraper commands during MFA relay
        self._last_plan = None  # last executed Plan, demoted if the user corrects us

    # -- registration -------------------------------------------------------

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def set_plugin_names(self, names: list[str]) -> None:
        self._plugin_names = names

    def register_command(self, cmd: Command) -> None:
        if cmd.name in self._builtin_commands:
            raise ValueError(f"Cannot override builtin command: /{cmd.name}")
        self._command_registry[cmd.name] = cmd

    def register_nl_handler(self, handler) -> None:
        self._nl_handlers.append(handler)
        if handler.intent_id:
            self._intent_registry[handler.intent_id] = handler

    def register_callback(self, callback) -> None:
        self._callback_registry[callback.prefix] = callback

    def intent_catalog(self) -> list[dict]:
        return [
            {
                "intent_id": intent_id,
                "description": h.description,
                "examples": h.examples,
            }
            for intent_id, h in self._intent_registry.items()
        ]

    def _ctx(self) -> AppContext:
        return AppContext(
            store=self._store, vault=self._vault, brain=self._brain,
            bot=self, scheduler=self._scheduler, config=self._config,
            profile=self._profile, learning=self._learning,
            ledger=self._ledger, stats=self._stats,
        )

    # -- lifecycle ------------------------------------------------------------

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
            "stats": self._handle_stats,
            "errors": self._handle_errors,
            "help": self._handle_help,
            "plugins": self._handle_plugins,
        }
        for name, handler in builtins.items():
            self._app.add_handler(CommandHandler(name, handler))

        for cmd_name, cmd in self._command_registry.items():
            self._app.add_handler(CommandHandler(cmd_name, self._make_command(cmd)))

        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        self._register_voice()

        from pa.core import photos
        self._app.add_handler(
            MessageHandler(
                filters.PHOTO,
                lambda u, c: self._guarded_media(photos.handle_photo, u, c),
            )
        )

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    def _make_command(self, cmd: Command):
        async def h(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not self._check_auth(update):
                return
            try:
                result = await cmd.handler(self._ctx(), update, context)
            except Exception as e:
                if self._ledger is not None:
                    await self._ledger.record(e, source=f"command:/{cmd.name}")
                # An LLM-credential failure gets the actionable message; anything
                # else still shows the raw error, which is genuinely useful for a
                # real bug.
                result = brain_failure_message(e) or f"/{cmd.name} failed: {e}"
            if result:
                await self._send_long(update, result)
        return h

    async def _guarded_media(self, handler, update, context) -> None:
        if not self._check_auth(update):
            return
        try:
            await handler(update, context, self)
        except Exception as e:
            # Without this, a broken ffmpeg/whisper/vision path dies into
            # PTB's logger — no ledger entry, no reply, silent forever.
            if self._ledger is not None:
                await self._ledger.record(e, source="media_handler")
            try:
                await self._send_raw(
                    update.effective_chat.id,
                    brain_failure_message(e)
                    or "I couldn't process that — the error has been recorded.",
                )
            except Exception:
                pass

    def _register_voice(self) -> None:
        """Voice notes transcribe locally (Whisper) and route like typed text."""
        from pa.core import voice
        if not voice.available():
            logger.info("whisper not installed — voice notes disabled")
            return
        self._app.add_handler(
            MessageHandler(
                filters.VOICE,
                lambda u, c: self._guarded_media(voice.handle_voice, u, c),
            )
        )

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def _send_raw(self, chat_id, text: str, **kwargs) -> None:
        # Try HTML first so plugins can return rich formatting (<b>, <code>,
        # <pre>); anything that is not valid Telegram-HTML falls back to the
        # plain text we always sent.
        try:
            await self._app.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="HTML", **kwargs)
        except Exception:
            await self._app.bot.send_message(chat_id=chat_id, text=text, **kwargs)

    async def send_message(self, text: str) -> None:
        user_id = self._config.get("telegram_user_id")
        if not (self._app and user_id):
            return
        for chunk in self._chunks(text):
            await self._send_raw(user_id, chunk)

    async def send_approval(
        self, text: str, approve_data: str, reject_data: str,
        approve_label: str = "✅ Approve", reject_label: str = "❌ Reject",
    ) -> None:
        """Send a message with Approve/Reject inline buttons.

        approve_data/reject_data are callback payloads like "repair:approve:42"
        (max 64 bytes per Telegram)."""
        user_id = self._config.get("telegram_user_id")
        if not (self._app and user_id):
            return
        chunks = self._chunks(text)
        for chunk in chunks[:-1]:
            await self._send_raw(user_id, chunk)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(approve_label, callback_data=approve_data),
            InlineKeyboardButton(reject_label, callback_data=reject_data),
        ]])
        await self._send_raw(user_id, chunks[-1], reply_markup=keyboard)

    async def send_buttons(self, text: str, rows) -> None:
        """Send a message with an arbitrary inline keyboard.

        rows: list of button rows, each row a list of (label, callback_data)
        tuples — callback_data routes to plugin Callback handlers by prefix."""
        user_id = self._config.get("telegram_user_id")
        if not (self._app and user_id):
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(lbl, callback_data=data) for lbl, data in row]
            for row in rows
        ])
        await self._send_raw(user_id, text, reply_markup=kb)

    async def _handle_callback(self, update: Update, context) -> None:
        query = update.callback_query
        if update.effective_user.id != self._config.get("telegram_user_id", 0):
            await query.answer()
            return
        data = query.data or ""
        prefix, _, payload = data.partition(":")
        callback = self._callback_registry.get(prefix)
        if callback is None:
            await query.answer("Unknown action.")
            return
        try:
            result = await callback.handler(self._ctx(), update, payload)
        except Exception as e:
            if self._ledger is not None:
                await self._ledger.record(e, source=f"callback:{prefix}")
            await query.answer("That action failed — recorded.")
            return
        await query.answer()
        # Freeze the buttons so the choice can't be double-tapped
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not clear inline keyboard", exc_info=True)
        if result:
            await self.send_message(result)

    # -- builtin handlers -------------------------------------------------------

    def _check_auth(self, update: Update) -> bool:
        return update.effective_user.id == self._config.get("telegram_user_id", 0)

    async def _handle_unlock(self, update, context) -> None:
        if not self._check_auth(update):
            return
        await self._delete_msg(context.user_data.pop("_prompt_message", None))
        prompt_msg = await update.message.reply_text("Send your master password:")
        context.user_data["awaiting_password"] = True
        context.user_data["_prompt_message"] = prompt_msg

    async def _handle_lock(self, update, context) -> None:
        if not self._check_auth(update):
            return
        self._vault.lock()
        await update.message.reply_text("Vault locked.")

    async def _handle_status(self, update, context) -> None:
        if not self._check_auth(update):
            return
        lines = [
            f"Vault: {'unlocked' if self._vault.is_unlocked else 'locked'}",
            f"Plugins: {', '.join(self._plugin_names) or 'none'}",
        ]
        if self._scheduler is not None:
            jobs = self._scheduler.get_job_names()
            lines.append(f"Jobs: {len(jobs)} scheduled")
        lines.append(f"Brain: {await self._brain_health()}")
        await update.message.reply_text("\n".join(lines))

    async def _brain_health(self) -> str:
        """One-line LLM backend status for /status.

        Albus spent a month reporting "All systems up" while every reasoning call
        failed, because nothing surfaced the backend's auth state. A cheap live
        probe is worth it: this is the single most load-bearing dependency, and
        its failure is otherwise invisible until something tries to think.
        """
        brain = getattr(self, "_brain", None)
        if brain is None:
            return "not wired"
        try:
            # context_id=None keeps this stateless so a health probe never
            # pollutes the conversation window.
            await brain.complete("ping", tier=Tier.PARSE, max_tokens=1, context_id=None)
            return "OK"
        except Exception as e:  # noqa: BLE001 — any failure is a status, not a crash
            blob = str(e).lower()
            if any(m in blob for m in _AUTH_FAILURE_MARKERS):
                return "UNAUTHENTICATED — run cli-proxy-api -claude-login (see /errors)"
            return f"erroring ({type(e).__name__})"

    async def _handle_stats(self, update, context) -> None:
        if not self._check_auth(update):
            return
        if self._stats is None:
            await update.message.reply_text("Stats not wired.")
            return
        await update.message.reply_text(await self._stats.reflex_report())

    async def _handle_errors(self, update, context) -> None:
        if not self._check_auth(update):
            return
        if self._ledger is None:
            await update.message.reply_text("Ledger not wired.")
            return
        rows = await self._ledger.recent(limit=8)
        if not rows:
            await update.message.reply_text("No recorded errors. Splendid.")
            return
        lines = ["**Recent failures**\n"]
        for r in rows:
            lines.append(
                f"[{r['signature']}] {r['source']} — {r['error_type']} "
                f"(x{r['count']}, last {r['last_seen']})\n  {r['message'][:120]}"
            )
        await self._send_long(update, "\n".join(lines))

    async def _handle_help(self, update, context) -> None:
        if not self._check_auth(update):
            return
        lines = [
            f"**{NAME} Commands**\n",
            "/unlock - Enter master password",
            "/lock - Lock vault",
            "/addcred - Add institution credentials",
            "/creds - List stored credentials",
            "/delcred - Remove credentials",
            "/status - System status",
            "/stats - Reflex rate & LLM usage",
            "/errors - Recent failures",
            "/prefs - View/clear learned preferences",
            "/plugins - Active plugins",
        ]
        for name, cmd in sorted(self._command_registry.items()):
            lines.append(f"/{name} - {cmd.description}")
        lines.append("/help - This message")
        await self._send_long(update, "\n".join(lines))

    async def _handle_plugins(self, update, context) -> None:
        if not self._check_auth(update):
            return
        text = (
            "Active plugins:\n" + "\n".join(f"  - {n}" for n in self._plugin_names)
            if self._plugin_names else "No plugins loaded."
        )
        await update.message.reply_text(text)

    async def _handle_prefs(self, update, context) -> None:
        if not self._check_auth(update):
            return
        if self._learning is None:
            await update.message.reply_text("Learning store not wired.")
            return
        if context.args and context.args[0].lower() == "clear":
            for pref in await self._learning.all_of_kind("preference", limit=1000):
                await self._learning.forget(pref["id"])
            await update.message.reply_text("All preferences cleared.")
            return
        prefs = await self._learning.all_of_kind("preference", limit=15)
        if not prefs:
            await update.message.reply_text(
                "No preferences learned yet. Just tell me what you like or don't like!"
            )
            return
        lines = [f"**Learned Preferences** ({len(prefs)} shown)\n"]
        for i, p in enumerate(prefs, 1):
            lines.append(f"{i}. {p['value'].get('text', p['key'])}")
        lines.append("\nUse /prefs clear to reset.")
        await self._send_long(update, "\n".join(lines))

    async def _handle_addcred(self, update, context) -> None:
        if not self._check_auth(update):
            return
        institution = " ".join(context.args) if context.args else None
        if institution:
            context.user_data["addcred"] = {"institution": institution, "step": "url"}
            prompt = await update.message.reply_text(f"Login page URL for {institution}:")
        else:
            context.user_data["addcred"] = {"step": "institution"}
            prompt = await update.message.reply_text(
                "Institution name (e.g. wellsfargo, synchrony):"
            )
        context.user_data["_addcred_prompt"] = prompt

    async def _handle_creds(self, update, context) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        names = self._vault.institutions()
        if not names:
            await update.message.reply_text("No credentials stored. Use /addcred to add some.")
            return
        lines = ["Stored credentials:\n"]
        for inst in names:
            data = self._vault.get(inst) or {}
            username = data.get("username", "?")
            masked = (
                username[:2] + "*" * (len(username) - 4) + username[-2:]
                if len(username) > 4 else "****"
            )
            url = (data.get("url") or "").split("//")[-1][:30] or "no URL"
            lines.append(f"  {inst}: {masked} ({url})")
        await update.message.reply_text("\n".join(lines))

    async def _handle_delcred(self, update, context) -> None:
        if not self._check_auth(update):
            return
        if not self._vault.is_unlocked:
            await update.message.reply_text("Vault is locked. Send /unlock first.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /delcred <institution>")
            return
        institution = " ".join(context.args)
        if await self._vault.remove(institution):
            await update.message.reply_text(f"Credentials for '{institution}' removed.")
        else:
            await update.message.reply_text(f"No credentials found for '{institution}'.")

    # -- message flow ------------------------------------------------------------

    async def _handle_message(self, update: Update, context) -> None:
        if not self._check_auth(update):
            return
        if await self._handle_password_entry(update, context):
            return
        if await self._handle_addcred_entry(update, context):
            return
        if await self._handle_mfa_entry(update):
            return

        text = update.message.text
        await self._detect_preference(text)
        try:
            await self._route_message(text, update)
        except Exception as e:
            if self._ledger is not None:
                await self._ledger.record(e, source="route_message")
            # "Try again?" is a lie when the backend has no credentials — it will
            # fail identically forever. Say what is actually wrong.
            await self._send_raw(
                update.effective_chat.id,
                brain_failure_message(e)
                or "Something went sideways handling that — it's been recorded. Try again?",
            )

    async def _handle_password_entry(self, update, context) -> bool:
        if not context.user_data.get("awaiting_password"):
            return False
        context.user_data["awaiting_password"] = False
        password = update.message.text
        await self._delete_msg(update.message)
        await self._delete_msg(context.user_data.pop("_prompt_message", None))
        try:
            was_new = not self._vault.exists
            await self._vault.unlock(password)
            if self._vault.derived_key and hasattr(self._store, "reconnect_encrypted"):
                await self._store.reconnect_encrypted(self._vault.derived_key)
            msg = (
                "Vault created and unlocked. Remember this password!"
                if was_new else "Vault unlocked."
            )
            await update.effective_chat.send_message(msg)
        except Exception:
            await update.effective_chat.send_message("Wrong password. Try /unlock again.")
        return True

    async def _handle_addcred_entry(self, update, context) -> bool:
        addcred = context.user_data.get("addcred")
        if not addcred:
            return False
        step = addcred["step"]
        text = update.message.text.strip()
        await self._delete_msg(context.user_data.pop("_addcred_prompt", None))
        await self._delete_msg(update.message)

        async def prompt(msg: str) -> None:
            context.user_data["_addcred_prompt"] = (
                await update.effective_chat.send_message(msg)
            )

        if step == "institution":
            addcred.update(institution=text, step="url")
            await prompt(f"Login page URL for {text}:")
        elif step == "url":
            addcred.update(url=text, step="username")
            await prompt(f"Username for {addcred['institution']}:")
        elif step == "username":
            addcred.update(username=text, step="password")
            await prompt(f"Password for {addcred['institution']}:")
        elif step == "password":
            institution = addcred["institution"]
            creds = {
                "url": addcred.get("url", ""),
                "username": addcred["username"],
                "password": text,
            }
            del context.user_data["addcred"]
            try:
                await self._vault.add(institution, creds)
                await update.effective_chat.send_message(
                    f"Credentials saved for {institution}."
                )
            except Exception as e:
                await update.effective_chat.send_message(f"Error saving: {e}")
        return True

    async def _handle_mfa_entry(self, update) -> bool:
        code = update.message.text.strip()
        if self._mfa_subprocess is not None:
            proc = self._mfa_subprocess
            try:
                proc.stdin.write(
                    json.dumps({"event": "mfa_code", "code": code}).encode() + b"\n"
                )
                await proc.stdin.drain()
                await update.message.reply_text("MFA code sent. Continuing scrape...")
            except Exception as e:
                await update.message.reply_text(f"Failed to relay MFA code: {e}")
            finally:
                self._mfa_subprocess = None
            return True
        pending = self._mfa_bridge.pending_institutions()
        # Only swallow messages that actually look like MFA codes — while a
        # scrape waits (up to 5 min), ordinary questions must still route.
        if pending and re.fullmatch(r"\d{4,8}", code):
            inst = pending[0]
            await self._mfa_bridge.provide_mfa(inst, code)
            await update.message.reply_text(f"MFA code sent to {inst}.")
            return True
        return False

    async def _detect_preference(self, text: str) -> None:
        if self._learning is None:
            return
        lower = text.lower()
        if any(p in lower for p in _PREFERENCE_PHRASES):
            # Preferences are replayed into every future system prompt, so
            # scrub PII/secrets NOW — the brain's prompt scrubbing does not
            # re-cover stored preference text.
            from pa.core.scrub import scrub
            clean, _ = scrub(text[:200])
            await self._learning.remember(
                "preference", clean, {"text": clean},
                source="auto_detected", confidence=0.6,
            )

    _CORRECTION_MARKERS = (
        "not what i asked", "not what i meant", "that's not what",
        "thats not what", "didn't ask", "didnt ask", "no idea what",
        "wrong answer", "not even close", "why did you", "i said",
    )

    async def _route_message(self, text: str, update: Update) -> None:
        """Reflex ladder: L0/L1 plan → execute + chain → chat fallback."""
        # A correction means the last plan solved the wrong problem even though
        # its handlers "succeeded" — demote it so it doesn't calcify into L0.
        tl = text.lower()
        if self._last_plan is not None and any(m in tl for m in self._CORRECTION_MARKERS):
            await self._reflex.record_outcome(self._last_plan, ok=False)
            self._last_plan = None

        recent = self._brain.context("main").window()
        quoted = getattr(update.message.reply_to_message, "text", None)
        if quoted:
            recent = recent + [
                {"role": "assistant", "content": f"[user is replying to this] {quoted[:400]}"}
            ]
        plan = await self._reflex.route(text, recent_context=recent)
        self._last_plan = plan

        if not plan.actions:
            if plan.missing:
                await self._record_capability_gap(text, plan.missing)
                await self._send_long(
                    update,
                    f"I can't do that yet — {plan.missing}\n\n"
                    "I've logged it as a capability gap so it makes the build list.",
                )
                return
            response = await self._brain.complete(
                text, tier=Tier.REASON, context_id="main", max_tokens=2048
            )
            await self._send_long(update, response)
            return

        ctx = self._ctx()
        results: list[str] = []
        failures: list[str] = []
        accumulated = ""
        for action in plan.actions:
            handler = self._intent_registry.get(action.get("intent_id", ""))
            if handler is None:
                continue
            handler_input = text
            if accumulated:
                handler_input = f"{text}\n\n[Context from prior steps: {accumulated}]"
            try:
                result = await handler.handler(ctx, handler_input, update)
            except Exception as e:
                if self._ledger is not None:
                    await self._ledger.record(e, source=f"nl:{handler.intent_id}")
                failures.append(f"({handler.intent_id} hit a snag: {e})")
                continue
            if result:
                results.append(result)
                accumulated += f"\n{handler.intent_id}: {result}"

        # Only genuine handler output counts as success — error strings must
        # not teach the reflex layer that a broken route "worked", and a plan
        # with ANY failing step must not be reinforced (partial success would
        # replay the half-broken plan at L0 forever).
        ok = bool(results) and not failures
        await self._reflex.record_outcome(plan, ok)
        if failures:
            results.extend(failures)

        if not ok:
            response = await self._brain.complete(
                text, tier=Tier.REASON, context_id="main", max_tokens=2048
            )
            await self._send_long(update, response)
            return

        if len(results) == 1:
            final = results[0]
        elif plan.synthesize:
            combined = "\n\n---\n\n".join(results)
            final = await self._brain.complete(
                f"User asked: '{text}'\n\nResults from actions:\n{combined}\n\n"
                "Combine these into a single, natural response. Be concise.",
                tier=Tier.REASON, max_tokens=2048,
            )
        else:
            final = "\n\n".join(results)

        await self._send_long(update, final)
        main_ctx = self._brain.context("main")
        main_ctx.add("user", text)
        main_ctx.add("assistant", final)

    async def _record_capability_gap(self, text: str, missing: str) -> None:
        """A request we understood but cannot fulfill — remember it so the
        weekly self-report can turn repeated gaps into build priorities."""
        if self._learning is None:
            return
        from pa.core.reflex import pattern_key
        key = pattern_key(text) or missing[:80]
        try:
            await self._learning.remember(
                "gap", key, {"request": text[:300], "missing": missing},
                source="l1_planner",
            )
        except Exception:
            logger.exception("Failed to record capability gap")

    # -- utilities ------------------------------------------------------------

    @staticmethod
    async def _delete_msg(msg: Any) -> None:
        if msg:
            try:
                await msg.delete()
            except Exception:
                logger.debug("Could not delete a Telegram message", exc_info=True)

    @classmethod
    def _chunks(cls, text: str, chunk_size: int = 4000) -> list[str]:
        chunks = []
        while text:
            if len(text) <= chunk_size:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, chunk_size)
            if split_at <= 0:
                split_at = chunk_size
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def _send_long(self, update: Update, text: str) -> None:
        for chunk in self._chunks(text):
            # HTML first (plugins may return rich formatting), plain fallback
            try:
                await update.message.reply_text(chunk, parse_mode="HTML")
            except Exception:
                await update.message.reply_text(chunk)
