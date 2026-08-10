"""Reflex router — the L0/L1 ladder.

L0: a message that looks like something we've handled before replays its
learned action plan with zero LLM calls. L1: novel messages get one cheap
PARSE-tier planning call whose result is immediately learned, so the same
shape of request never escalates again. record_outcome() feeds success or
failure back so bad plans decay instead of haunting the router forever.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pa.core.brain import Brain, Tier
from pa.core.learning import LearningStore

logger = logging.getLogger(__name__)

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am",
    "i", "me", "my", "you", "your", "we", "our", "he", "she", "it",
    "do", "does", "did", "have", "has", "had", "can", "could", "would",
    "should", "will", "shall", "may", "might", "to", "of", "in", "for",
    "on", "at", "by", "from", "with", "and", "or", "but", "not", "no",
    "if", "so", "up", "out", "just", "about", "that", "this", "what",
    "how", "much", "many", "some", "any", "all", "very", "too", "also",
    "being", "get", "got", "go", "going", "let", "please",
    "hey", "hi", "hello", "ok", "yeah", "yes", "uh", "um",
})


def pattern_key(message: str) -> str:
    """Significant-word signature used as the learned-plan key."""
    import re
    words = set(re.findall(r"[a-z]+", message.lower())) - _STOP_WORDS
    return " ".join(sorted(words))


@dataclass
class Plan:
    actions: list[dict] = field(default_factory=list)
    synthesize: bool = False
    source: str = "none"          # "l0" | "l1" | "none" (none = general chat)
    learning_id: int | None = None
    missing: str = ""             # capability the request needs but no action provides


class Reflex:
    SIMILARITY_THRESHOLD = 0.6

    def __init__(self, learning: LearningStore, brain: Brain, stats=None):
        self._learning = learning
        self._brain = brain
        self._stats = stats
        self._catalog: list[dict] = []

    def set_catalog(self, handlers: list[dict]) -> None:
        """handlers: [{intent_id, description, examples}] from registered plugins."""
        self._catalog = handlers

    async def route(
        self, text: str, recent_context: list[dict] | None = None
    ) -> Plan:
        """L0 learned match, else L1 plan-and-learn, else general chat (none)."""
        key = pattern_key(text)
        if len(key.split()) >= 2:
            hit = await self._learning.recall("plan", key)
            if hit is None:
                hit = await self._learning.similar(
                    "plan", key, threshold=self.SIMILARITY_THRESHOLD
                )
            if hit is not None:
                await self._bump("handled_l0")
                value = hit["value"]
                return Plan(
                    actions=value.get("actions", []),
                    synthesize=value.get("synthesize", False),
                    source="l0",
                    learning_id=hit["id"],
                )

        plan = await self._plan_with_llm(text, recent_context)
        if plan.actions:
            await self._bump("handled_l1")
        else:
            await self._bump("handled_l2")  # falls through to REASON-tier chat
        return plan

    async def record_outcome(self, plan: Plan, ok: bool) -> None:
        """Confirm plans that worked; decay plans that failed."""
        if plan.learning_id is None:
            return
        if ok:
            await self._learning.confirm(plan.learning_id)
        else:
            await self._learning.demote(plan.learning_id)

    # -- L1 ---------------------------------------------------------------

    async def _plan_with_llm(
        self, text: str, recent_context: list[dict] | None
    ) -> Plan:
        if not self._catalog:
            return Plan()
        catalog_lines = []
        for h in self._catalog:
            line = f"- {h['intent_id']}: {h['description']}"
            if h.get("examples"):
                line += f" (e.g. {', '.join(repr(e) for e in h['examples'][:2])})"
            catalog_lines.append(line)

        context_str = ""
        if recent_context:
            turns = recent_context[-6:]
            context_str = "\n\nRecent conversation:\n" + "\n".join(
                f"{t['role']}: {t['content'][:300]}" for t in turns
            )

        system = (
            "You are an action planner for a personal assistant. Given the "
            "user's message, plan what actions to take from the catalog.\n\n"
            "Available actions:\n" + "\n".join(catalog_lines) + context_str + "\n\n"
            "Rules:\n"
            '- Return JSON: {"actions": [{"intent_id": "x", "reason": "why"}], '
            '"synthesize": false}\n'
            "- Order matters: each action's result feeds into the next\n"
            '- Greeting, opinion, or general chat: {"actions": []}\n'
            "- Follow-ups refer to prior conversation — use context\n"
            '- "synthesize": true when multiple results should merge into one reply\n'
            "- Every action you pick must directly do what the user asked. An action "
            "that merely relates to the topic is WRONG — never pick one just to do "
            "something\n"
            '- If the request needs a capability no catalog action provides, return '
            '{"actions": [], "missing": "<one line: what it would take to fulfill '
            'this>"}. Admitting the gap is a good outcome — it gets the capability '
            "built"
        )

        try:
            result = await self._brain.query_json(
                text, tier=Tier.PARSE, system=system, max_tokens=300
            )
        except Exception:
            logger.exception("L1 planning failed; treating as general chat")
            return Plan()

        actions = [
            a for a in result.get("actions", [])
            if isinstance(a, dict) and a.get("intent_id")
        ]
        plan = Plan(
            actions=actions,
            synthesize=bool(result.get("synthesize", False)),
            source="l1" if actions else "none",
            missing="" if actions else str(result.get("missing") or "").strip(),
        )
        if actions:
            key = pattern_key(text)
            if len(key.split()) >= 2:
                plan.learning_id = await self._learning.remember(
                    "plan", key,
                    {"actions": actions, "synthesize": plan.synthesize},
                    source="l1_planner",
                )
                await self._bump("learnings_created")
        return plan

    async def _bump(self, metric: str) -> None:
        if self._stats is None:
            return
        try:
            await self._stats.bump(metric)
        except Exception:
            logger.exception("Stats bump failed for %s", metric)
