"""Brain v2 — the single choke point for all LLM traffic.

Backends are config, not code: capability tiers (PARSE, REASON) map to
ordered backend lists in config. Today that's CLIProxyAPI fronting a Claude
Max subscription; when the home-network LLM exists it gets added to config
(trusted: true) and takes over tiers with zero code changes.

Everything that must happen on every call lives in complete(): scrubbing for
untrusted backends, ordered backend fallback, retries with backoff, stats,
the error ledger, and per-context conversation isolation (each agent in the
eventual AI-company gets its own BrainContext).

Config shape ("llm" section):
  {
    "backends": {
      "cliproxy": {
        "base_url": "http://localhost:8317/v1",
        "trusted": false,
        "models": {"parse": "claude-haiku-4-5", "reason": "claude-sonnet-4-5"}
      }
    },
    "tiers": {"parse": ["cliproxy"], "reason": ["cliproxy"]},
    "scrub_untrusted": true
  }
"""
from __future__ import annotations

import asyncio
import base64
import enum
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from pa.core.exceptions import BrainAPIError
from pa.core.scrub import restore as scrub_restore
from pa.core.scrub import scrub

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS core_conversations_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_core_conversations_v2_ctx
    ON core_conversations_v2(context_id, id);
"""

MAX_TURNS_IN_PROMPT = 10
MAX_TURNS_KEPT = 40
MAX_MSG_CHARS = 2000
RETRIES_PER_BACKEND = 2


class Tier(enum.Enum):
    PARSE = "parse"      # cheap structured extraction / classification
    REASON = "reason"    # analysis, advice, planning, conversation


@dataclass
class Backend:
    name: str
    base_url: str
    trusted: bool = False
    api_key_env: str = ""
    models: dict[str, str] = field(default_factory=dict)

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "") or "not-needed"


class BrainContext:
    """An isolated conversation window."""

    def __init__(self, context_id: str):
        self.context_id = context_id
        self.system_fragments: list[str] = []
        self.turns: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content[:MAX_MSG_CHARS]})
        if len(self.turns) > MAX_TURNS_KEPT:
            self.turns = self.turns[-MAX_TURNS_KEPT:]

    def window(self) -> list[dict[str, str]]:
        return self.turns[-MAX_TURNS_IN_PROMPT:]


class Brain:
    def __init__(
        self, config: dict[str, Any], store=None, stats=None, ledger=None, learning=None
    ):
        llm = config.get("llm") or {}
        self._backends: dict[str, Backend] = {
            name: Backend(
                name=name,
                base_url=b["base_url"],
                trusted=bool(b.get("trusted", False)),
                api_key_env=b.get("api_key_env", ""),
                models=dict(b.get("models") or {}),
            )
            for name, b in (llm.get("backends") or {}).items()
        }
        self._tiers: dict[str, list[str]] = dict(llm.get("tiers") or {})
        self._scrub_untrusted: bool = bool(llm.get("scrub_untrusted", True))
        # Billing guard, by construction: the owner's standing order is that
        # LLM traffic must never hit a paid provider API — only his local
        # Max-subscription proxy (or, later, a home LLM box). Refuse at boot
        # if any backend points at a known paid endpoint, so a stray config
        # edit can't silently start billing.
        _PAID_HOSTS = (
            "api.anthropic.com", "api.openai.com", "openai.azure.com",
            "generativelanguage.googleapis.com", "api.cohere.ai",
            "api.mistral.ai", "api.groq.com", "api.perplexity.ai",
        )
        for b in self._backends.values():
            host = b.base_url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
            if any(host == ph or host.endswith("." + ph) for ph in _PAID_HOSTS):
                raise ValueError(
                    f"LLM backend '{b.name}' points at paid provider '{host}' — "
                    "refusing to start (billing guard: local proxy only)."
                )
        self._store = store
        self._stats = stats
        self._ledger = ledger
        self._learning = learning
        self._contexts: dict[str, BrainContext] = {}
        self._clients: dict[str, Any] = {}
        self._base_system: str = ""

    # -- wiring -------------------------------------------------------------

    def set_base_system_prompt(self, text: str) -> None:
        self._base_system = text

    def context(self, context_id: str = "main") -> BrainContext:
        if context_id not in self._contexts:
            self._contexts[context_id] = BrainContext(context_id)
        return self._contexts[context_id]

    async def load_from_db(self) -> None:
        if self._store is None:
            return
        rows = await self._store.fetchall(
            "SELECT context_id, role, content FROM core_conversations_v2 ORDER BY id"
        )
        for r in rows:
            self.context(r["context_id"]).add(r["role"], r["content"])

    def schema_sql(self) -> str:
        return SCHEMA

    # -- the choke point ------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        *,
        tier: Tier = Tier.PARSE,
        system: str | None = None,
        context_id: str | None = None,
        image: bytes | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """All LLM traffic passes through here. context_id=None means a
        stateless call (no conversation memory). Raises BrainAPIError when
        every backend for the tier is exhausted."""
        backend_names = self._tiers.get(tier.value) or list(self._backends)
        if not backend_names:
            raise BrainAPIError("No LLM backends configured")

        last_err: Exception | None = None
        for backend_name in backend_names:
            backend = self._backends.get(backend_name)
            if backend is None or not backend.models.get(tier.value):
                continue
            model = backend.models[tier.value]

            needs_scrub = self._scrub_untrusted and not backend.trusted
            sent_prompt, restore_map = scrub(prompt) if needs_scrub else (prompt, {})
            prefs = await self._preference_fragment() if context_id is not None else ""
            full_system = "\n\n".join(p for p in (system, prefs) if p) or None
            # The system prompt carries learned preferences (raw user text) —
            # scrub it too or PII pasted there bypasses the prompt scrubbing.
            if needs_scrub and full_system:
                full_system, sys_map = scrub(full_system)
                restore_map = {**restore_map, **sys_map}
            messages = self._build_messages(
                sent_prompt, full_system, context_id, image, scrub_history=needs_scrub
            )

            for attempt in range(RETRIES_PER_BACKEND):
                try:
                    text = await self._call(
                        backend, model, messages, max_tokens, temperature
                    )
                    if restore_map:
                        text = scrub_restore(text, restore_map)
                    await self._record_turns(context_id, prompt, text)
                    await self._bump(f"llm_calls.{backend.name}.{tier.value}")
                    return text
                except Exception as e:
                    last_err = e
                    logger.warning(
                        "LLM call failed (%s/%s attempt %d): %s",
                        backend.name, model, attempt + 1, e,
                    )
                    if attempt < RETRIES_PER_BACKEND - 1:
                        await asyncio.sleep(2 ** attempt)

        await self._bump("llm_errors")
        err = BrainAPIError(f"All backends failed for tier '{tier.value}': {last_err}")
        if self._ledger is not None:
            await self._ledger.record(err, source="brain")
        raise err

    async def query_json(
        self,
        prompt: str,
        *,
        tier: Tier = Tier.PARSE,
        system: str | None = None,
        image: bytes | None = None,
        max_tokens: int = 1024,
    ) -> dict:
        """The one JSON helper every caller uses (no more copy-pasted parsing)."""
        json_system = ((system or "") + (
            "\nRespond with ONLY a valid JSON object. No prose, no markdown fences."
        )).strip()
        text = await self.complete(
            prompt, tier=tier, system=json_system, context_id=None,
            image=image, max_tokens=max_tokens, temperature=0.0,
        )
        return self.extract_json(text)

    # -- helpers --------------------------------------------------------------

    def _build_messages(
        self,
        prompt: str,
        system: str | None,
        context_id: str | None,
        image: bytes | None,
        scrub_history: bool = False,
    ) -> list[dict[str, Any]]:
        parts = [p for p in (self._base_system, system) if p]
        if context_id is not None:
            parts.extend(self.context(context_id).system_fragments)
        messages: list[dict[str, Any]] = []
        if parts:
            messages.append({"role": "system", "content": "\n\n".join(parts)})
        if context_id is not None:
            # History is stored raw; scrub it on the way out to untrusted
            # backends so PII from earlier turns never leaves either.
            for turn in self.context(context_id).window():
                content = turn["content"]
                if scrub_history:
                    content, _ = scrub(content)
                messages.append({"role": turn["role"], "content": content})
        if image is not None:
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(image).decode()
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            })
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    async def _call(
        self,
        backend: Backend,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> str:
        client = self._client(backend)
        resp = await client.chat.completions.create(
            model=model, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            await self._bump("llm_tokens_in", float(getattr(usage, "prompt_tokens", 0) or 0))
            await self._bump("llm_tokens_out", float(getattr(usage, "completion_tokens", 0) or 0))
        content = resp.choices[0].message.content
        if not content:
            raise BrainAPIError(f"Empty completion from {backend.name}/{model}")
        return content

    def _client(self, backend: Backend):
        if backend.name not in self._clients:
            from openai import AsyncOpenAI
            self._clients[backend.name] = AsyncOpenAI(
                base_url=backend.base_url, api_key=backend.api_key,
            )
        return self._clients[backend.name]

    async def _record_turns(
        self, context_id: str | None, prompt: str, reply: str
    ) -> None:
        if context_id is None:
            return
        ctx = self.context(context_id)
        ctx.add("user", prompt)
        ctx.add("assistant", reply)
        if self._store is None:
            return
        for role, content in (("user", prompt), ("assistant", reply)):
            await self._store.execute(
                "INSERT INTO core_conversations_v2 (context_id, role, content) "
                "VALUES (?, ?, ?)",
                (context_id, role, content[:MAX_MSG_CHARS]),
            )
        await self._store.execute(
            "DELETE FROM core_conversations_v2 WHERE context_id = ? AND id NOT IN "
            "(SELECT id FROM core_conversations_v2 WHERE context_id = ? "
            " ORDER BY id DESC LIMIT ?)",
            (context_id, context_id, MAX_TURNS_KEPT),
        )

    async def _preference_fragment(self) -> str:
        if self._learning is None:
            return ""
        try:
            prefs = await self._learning.all_of_kind("preference", limit=10)
        except Exception:
            logger.exception("Could not load preferences for system prompt")
            return ""
        if not prefs:
            return ""
        lines = "\n".join(f"- {p['value'].get('text', p['key'])}" for p in prefs)
        return f"User preferences (learned over time):\n{lines}"

    async def _bump(self, metric: str, value: float = 1.0) -> None:
        if self._stats is None:
            return
        try:
            await self._stats.bump(metric, value)
        except Exception:
            logger.exception("Stats bump failed for %s", metric)

    @staticmethod
    def extract_json(text: str) -> dict:
        """Extract a JSON object from model output. Tolerates markdown fences,
        surrounding prose, and trailing commas."""
        fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        text = fence.group(1).strip() if fence else text.strip()
        start = text.find("{")
        if start == -1:
            raise ValueError(f"No JSON object found in response: {text[:200]}")
        depth, end, in_string, escape = 0, -1, False, False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
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
        raw = text[start:end + 1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
