import asyncio
import os
import time
from collections import deque
from typing import Any

import anthropic

from pa.core.cost_tracker import CostTracker
from pa.core.exceptions import BrainAPIError
from pa.core.identity import NAME, PERSONA
from pa.core.tier import Tier

_MODEL_MAP = {
    Tier.FAST: "claude-haiku-4-5-20251001",
    Tier.STANDARD: "claude-sonnet-4-6",
    Tier.DEEP: "claude-opus-4-6",
}

_COST_PER_1K_TOKENS = {
    Tier.FAST: 0.001,
    Tier.STANDARD: 0.01,
    Tier.DEEP: 0.10,
}

_MAX_RETRIES = 3
_MAX_QUERIES_PER_HOUR = 30


class Brain:
    def __init__(self, config: Any):
        api_key_env = config.get("claude_api_key_env", "PA_CLAUDE_API_KEY")
        api_key = os.environ.get(api_key_env, "")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._cost_tracker = CostTracker(
            monthly_cap=config.get("cost_cap_monthly_usd", 20.0)
        )
        self._query_timestamps: deque[float] = deque()
        self._plugin_fragments: list[str] = []
        self._store = None
        self._conversation: list[dict] = []
        self._conv_max = 20  # sliding window
        self._preferences: list[str] = []

    def set_store(self, store) -> None:
        self._store = store

    def set_plugin_fragments(self, fragments: list[str]) -> None:
        self._plugin_fragments = fragments

    async def load_from_db(self, store) -> None:
        """Load conversation history and preferences from DB."""
        self._store = store
        await self._cost_tracker.load_from_db(store)
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
            "Rules:\n"
            "- Be direct and actionable\n"
            "- Reference specific data when available\n"
            "- If asked about something not in your data, say so\n"
            "- If the user corrects you or states a preference, acknowledge it"
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
        prompt = system_prompt or self.build_system_prompt()

        estimated_cost = _COST_PER_1K_TOKENS[tier] * 2
        self._cost_tracker.check_budget(estimated_cost)

        # Build messages with conversation history
        if use_conversation and self._conversation:
            messages = list(self._conversation[-10:])
            messages.append({"role": "user", "content": user_message})
        else:
            messages = [{"role": "user", "content": user_message}]

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=1024,
                    system=prompt,
                    messages=messages,
                )
                break
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
        else:
            raise BrainAPIError(f"Claude API error after {_MAX_RETRIES} retries: {last_error}") from last_error

        self._query_timestamps.append(time.monotonic())

        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        actual_cost = (total_tokens / 1000) * _COST_PER_1K_TOKENS[tier]
        self._cost_tracker.record(actual_cost)

        result = response.content[0].text

        # Remember this exchange
        if use_conversation:
            await self.remember_message("user", user_message)
            await self.remember_message("assistant", result)

        return result

    async def query_json(
        self,
        user_message: str,
        system_prompt: str,
        tier: Tier = Tier.STANDARD,
        image: bytes | None = None,
        max_tokens: int = 1024,
    ) -> dict:
        """Send a query expecting a JSON response. Skips rate limit (infrastructure use)."""
        model = self.select_model(tier)
        estimated_cost = _COST_PER_1K_TOKENS[tier] * 2
        self._cost_tracker.check_budget(estimated_cost)

        if image is not None:
            import base64
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image).decode(),
                    },
                },
                {"type": "text", "text": user_message},
            ]
        else:
            content = user_message

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": content}],
                )
                break
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
        else:
            raise BrainAPIError(f"Claude API error after {_MAX_RETRIES} retries: {last_error}") from last_error

        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        actual_cost = (total_tokens / 1000) * _COST_PER_1K_TOKENS[tier]
        self._cost_tracker.record(actual_cost)

        text = response.content[0].text
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
    def cost_tracker(self) -> CostTracker:
        return self._cost_tracker
