import asyncio
import json
import os
import time
from collections import deque
from typing import Any

from openai import AsyncOpenAI

from pa.core.exceptions import BrainAPIError
from pa.core.identity import NAME, PERSONA
from pa.core.tier import Tier

# CLIProxyAPI uses OpenAI format — all tiers route through Sonnet via subscription
# Haiku has tool-use reliability issues through CLIProxyAPI, so everything uses Sonnet
_MODEL_MAP = {
    Tier.FAST: "claude-sonnet-4-5-20250929",
    Tier.STANDARD: "claude-sonnet-4-5-20250929",
    Tier.DEEP: "claude-sonnet-4-5-20250929",
}

_MAX_RETRIES = 3
_MAX_QUERIES_PER_HOUR = 60  # Bumped — no per-query cost on subscription


class Brain:
    def __init__(self, config: Any):
        proxy_url = config.get("proxy_base_url", "http://localhost:8317/v1")
        self._client = AsyncOpenAI(
            base_url=proxy_url,
            api_key="not-needed",  # CLIProxyAPI with no auth providers
        )
        self._query_timestamps: deque[float] = deque()
        self._plugin_fragments: list[str] = []
        self._store = None
        self._conversation: list[dict] = []
        self._conv_max = 20  # sliding window
        self._preferences: list[str] = []
        self._intent_examples: list[dict] = []

    def set_store(self, store) -> None:
        self._store = store

    def set_plugin_fragments(self, fragments: list[str]) -> None:
        self._plugin_fragments = fragments

    async def load_from_db(self, store) -> None:
        """Load conversation history, preferences, and intent examples from DB."""
        self._store = store
        # Load recent conversation
        rows = await store.fetchall(
            "SELECT role, content FROM core_conversations ORDER BY id DESC LIMIT ?",
            (self._conv_max,)
        )
        self._conversation = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        # Load preferences
        rows = await store.fetchall(
            "SELECT preference FROM core_preferences ORDER BY id DESC LIMIT 50"
        )
        self._preferences = [r["preference"] for r in rows]
        # Load intent examples
        rows = await store.fetchall(
            "SELECT message, intent_id FROM core_intent_examples ORDER BY id DESC LIMIT 50"
        )
        self._intent_examples = [{"message": r["message"], "intent_id": r["intent_id"]} for r in rows]

    async def remember_message(self, role: str, content: str) -> None:
        """Add a message to conversation memory."""
        self._conversation.append({"role": role, "content": content})
        if len(self._conversation) > self._conv_max:
            self._conversation = self._conversation[-self._conv_max:]
        if self._store:
            await self._store.execute(
                "INSERT INTO core_conversations (role, content) VALUES (?, ?)",
                (role, content[:2000])
            )
            # Prune old messages (keep last 50)
            await self._store.execute(
                """DELETE FROM core_conversations WHERE id NOT IN
                   (SELECT id FROM core_conversations ORDER BY id DESC LIMIT 50)"""
            )

    async def learn_preference(self, preference: str, learned_from: str = "") -> None:
        """Save a user preference for future reference."""
        self._preferences.append(preference)
        if self._store:
            await self._store.execute(
                "INSERT INTO core_preferences (preference, learned_from) VALUES (?, ?)",
                (preference, learned_from)
            )

    def _check_rate_limit(self) -> None:
        now = time.monotonic()
        while self._query_timestamps and now - self._query_timestamps[0] > 3600:
            self._query_timestamps.popleft()
        if len(self._query_timestamps) >= _MAX_QUERIES_PER_HOUR:
            raise BrainAPIError(
                f"Rate limit: {_MAX_QUERIES_PER_HOUR} queries/hour exceeded. Try again later."
            )

    def select_model(self, tier: Tier) -> str:
        return _MODEL_MAP[tier]

    def build_system_prompt(self, plugin_fragments: list[str] | None = None) -> str:
        frags = plugin_fragments if plugin_fragments is not None else self._plugin_fragments
        parts = [PERSONA]
        parts.extend(frags)
        if self._preferences:
            pref_text = "\n".join(f"- {p}" for p in self._preferences[-10:])
            parts.append(f"User preferences (learned over time):\n{pref_text}")
        parts.append(
            "Your capabilities (what you can actually do):\n"
            "- Check Gmail, search for specific emails, extract balances from statements\n"
            "- Track debts, balances, spending by merchant, upcoming bills\n"
            "- Financial analysis via Bart the advisor\n"
            "- Manage kids schedules (Maddox & Asher)\n"
            "- Meal planning and grocery lists\n"
            "- Home maintenance tracking\n"
            "- Health/exercise logging\n"
            "- Task management with recurring reminders\n"
            "- Research topics\n"
            "You CANNOT: browse the web, send emails, move money, access real-time stock prices, "
            "make phone calls, or do anything outside these capabilities."
        )
        return "\n\n".join(parts)

    async def query(
        self,
        user_message: str,
        system_prompt: str | None = None,
        tier: Tier = Tier.FAST,
        use_conversation: bool = True,
    ) -> str:
        self._check_rate_limit()
        model = self.select_model(tier)

        # Detect preferences BEFORE building prompt so they're included immediately
        learned = None
        if use_conversation:
            learned = await self._detect_preference(user_message)

        prompt = system_prompt or self.build_system_prompt()

        # Build messages with conversation history
        messages = []
        # OpenAI format: system message first
        messages.append({"role": "system", "content": prompt})
        if use_conversation and self._conversation:
            messages.extend(self._conversation[-10:])
        messages.append({"role": "user", "content": user_message})

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    max_tokens=1024,
                    messages=messages,
                )
                break
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
        else:
            raise BrainAPIError(f"Proxy API error after {_MAX_RETRIES} retries: {last_error}") from last_error

        self._query_timestamps.append(time.monotonic())

        result = response.choices[0].message.content

        # Acknowledge the learned preference in the response
        if learned:
            result = f"📝 Noted — I'll remember that.\n\n{result}"

        # Remember this exchange
        if use_conversation:
            await self.remember_message("user", user_message)
            await self.remember_message("assistant", result)

        return result

    async def _detect_preference(self, message: str) -> str | None:
        """Auto-detect user preferences and corrections from messages.
        Returns the saved preference text if one was detected, else None."""
        ml = message.lower()
        correction_phrases = [
            "don't ", "dont ", "stop ", "never ", "quit ",
            "i don't want", "i dont want", "i don't care", "i dont care",
            "i don't need", "i dont need", "not interested in",
            "too many", "too much", "annoying", "stop sending",
            "i prefer", "i like", "i want", "always ", "make sure",
            "remember that", "keep in mind", "from now on",
        ]
        if any(phrase in ml for phrase in correction_phrases):
            pref = message.strip()[:200]
            await self.learn_preference(pref, learned_from="auto_detected")
            return pref
        return None

    async def log_error(self, source: str, error: Exception) -> None:
        """Self-healing: log errors to DB for tracking and pattern detection."""
        if not self._store:
            return
        try:
            error_type = type(error).__name__
            msg = str(error)[:500]
            # Check if we've seen this before
            existing = await self._store.fetchone(
                "SELECT id, count FROM core_errors WHERE source = ? AND error_type = ? AND resolved = 0",
                (source, error_type)
            )
            if existing:
                await self._store.execute(
                    "UPDATE core_errors SET count = count + 1, last_seen = CURRENT_TIMESTAMP, message = ? WHERE id = ?",
                    (msg, existing['id'])
                )
            else:
                await self._store.execute(
                    "INSERT INTO core_errors (source, error_type, message) VALUES (?, ?, ?)",
                    (source, error_type, msg)
                )
        except Exception:
            pass

    async def plan_actions(
        self,
        user_message: str,
        handler_catalog: list[dict],
        recent_context: list[dict] | None = None,
    ) -> dict:
        """Plan a sequence of actions to fulfill the user's request.

        Returns {"actions": [{"intent_id": str, "reason": str}], "synthesize": bool}
        Empty actions = general conversation.
        """
        catalog_lines = []
        for h in handler_catalog:
            line = f"- {h['intent_id']}: {h['description']}"
            if h.get("examples"):
                line += f" (e.g. {', '.join(repr(e) for e in h['examples'][:2])})"
            catalog_lines.append(line)
        catalog_str = "\n".join(catalog_lines)

        example_lines = ""
        if self._intent_examples:
            ex = self._intent_examples[-20:]
            example_lines = "\n\nLearned examples:\n" + "\n".join(
                f'"{e["message"]}" -> {e["intent_id"]}' for e in ex
            )

        context_str = ""
        if recent_context:
            turns = recent_context[-6:]
            context_str = "\n\nRecent conversation:\n" + "\n".join(
                f'{t["role"]}: {t["content"][:100]}' for t in turns
            )

        system = (
            "You are an action planner for a personal assistant. Given the user's message, "
            "plan what actions to take from the available catalog. Think step by step.\n\n"
            f"Available actions:\n{catalog_str}"
            f"{example_lines}{context_str}\n\n"
            "Rules:\n"
            "- Return JSON: {\"actions\": [{\"intent_id\": \"x\", \"reason\": \"why\"}], \"synthesize\": false}\n"
            "- Order matters: first action's result feeds into the next\n"
            "- For multi-step tasks, chain actions (e.g. search email → save debt)\n"
            "- If the message is a greeting, opinion, or general chat: {\"actions\": []}\n"
            "- If a follow-up refers to prior conversation, use context to pick the right action\n"
            "- 'synthesize': true if multiple action results should be combined into one response\n"
            "- When in doubt, pick an action — it's better to try and fail than to chat aimlessly\n"
            "- Raw JSON only, no markdown"
        )

        try:
            result = await self.query_json(
                user_message, system_prompt=system,
                tier=Tier.FAST, max_tokens=300,
            )
            actions = result.get("actions", [])
            synthesize = result.get("synthesize", False)
            return {"actions": actions, "synthesize": synthesize}
        except Exception:
            return {"actions": [], "synthesize": False}

    async def classify_intent(
        self,
        user_message: str,
        handler_catalog: list[dict],
        recent_context: list[dict] | None = None,
    ) -> list[dict]:
        """Classify user message into intents using Claude.

        Returns list of {"intent_id": str, "confidence": float}.
        Empty list = general conversation (no handler match).
        """
        # Build compact catalog
        catalog_lines = []
        for h in handler_catalog:
            line = f"- {h['intent_id']}: {h['description']}"
            if h.get("examples"):
                line += f" (e.g. {', '.join(repr(e) for e in h['examples'][:3])})"
            catalog_lines.append(line)
        catalog_str = "\n".join(catalog_lines)

        # Include learned examples (most recent 30)
        example_lines = ""
        if self._intent_examples:
            ex = self._intent_examples[-30:]
            example_lines = "\n\nLearned examples:\n" + "\n".join(
                f'"{e["message"]}" -> {e["intent_id"]}' for e in ex
            )

        # Include recent conversation for context
        context_str = ""
        if recent_context:
            turns = recent_context[-6:]  # last 3 exchanges
            context_str = "\n\nRecent conversation:\n" + "\n".join(
                f'{t["role"]}: {t["content"][:100]}' for t in turns
            )

        system = (
            "You are an intent classifier. Given the user's message, classify it into "
            "one or more intents from the catalog. Return raw JSON only.\n\n"
            f"Intent catalog:\n{catalog_str}"
            f"{example_lines}{context_str}\n\n"
            "Rules:\n"
            "- Return {\"intents\": [{\"intent_id\": \"x\", \"confidence\": 0.0-1.0}]}\n"
            "- Multiple intents OK for compound requests (e.g. 'check email and show balance')\n"
            "- If no intent matches (greeting, general chat, opinion), return {\"intents\": []}\n"
            "- confidence < 0.4 means don't route there\n"
            "- Context matters: follow-up questions belong with the prior topic\n"
            "- Raw JSON only, no markdown"
        )

        try:
            result = await self.query_json(
                user_message, system_prompt=system,
                tier=Tier.FAST, max_tokens=200,
            )
            intents = result.get("intents", [])
            # Filter low confidence
            return [i for i in intents if i.get("confidence", 0) >= 0.4]
        except Exception:
            return []

    async def confirm_intent(self, message: str, intent_id: str, source: str = "confirmed") -> None:
        """Save a confirmed intent routing for future learning."""
        if not self._store:
            return
        await self._store.execute(
            "INSERT INTO core_intent_examples (message, intent_id, source) VALUES (?, ?, ?)",
            (message[:200], intent_id, source)
        )
        self._intent_examples.append({"message": message[:200], "intent_id": intent_id})
        if len(self._intent_examples) > 100:
            self._intent_examples = self._intent_examples[-50:]

    async def query_json(
        self,
        user_message: str,
        system_prompt: str,
        tier: Tier = Tier.STANDARD,
        image: bytes | None = None,
        max_tokens: int = 1024,
    ) -> dict:
        """Send a query expecting a JSON response."""
        model = self.select_model(tier)

        messages = [{"role": "system", "content": system_prompt}]

        if image is not None:
            import base64
            content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64.b64encode(image).decode()}"
                    },
                },
                {"type": "text", "text": user_message},
            ]
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_message})

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=messages,
                )
                break
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
        else:
            raise BrainAPIError(f"Proxy API error after {_MAX_RETRIES} retries: {last_error}") from last_error

        text = response.choices[0].message.content
        return self._extract_json(text)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from response text, handling markdown code blocks."""
        import json as json_mod
        import re
        # Strip markdown fences first
        fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        else:
            text = text.strip()
        # Find outermost JSON object
        start = text.find("{")
        if start == -1:
            raise ValueError(f"No JSON object found in response: {text[:200]}")
        # Walk to find matching closing brace
        depth = 0
        end = -1
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == "\"" and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            raise ValueError(f"Unmatched braces in JSON: {text[:200]}")
        return json_mod.loads(text[start:end + 1])

    @property
    def cost_tracker(self):
        """Stub for backwards compatibility — no cost tracking on subscription."""
        return _NullCostTracker()


class _NullCostTracker:
    """No-op cost tracker for subscription mode."""
    total_this_month = 0.0
    remaining = float('inf')
    should_alert = False

    def record(self, cost: float) -> None:
        pass

    def check_budget(self, estimated_cost: float) -> None:
        pass

    async def load_from_db(self, store) -> None:
        pass
