import asyncio
import os
import time
from collections import deque
from typing import Any

import anthropic

from pa.brain.cost_tracker import CostTracker
from pa.brain.tier import Tier, classify_tier
from pa.config.config import Config
from pa.exceptions import BrainAPIError

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
    def __init__(self, config: Config):
        self._config = config
        api_key_env = config.get("claude_api_key_env", "PA_CLAUDE_API_KEY")
        api_key = os.environ.get(api_key_env, "")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._cost_tracker = CostTracker(
            monthly_cap=config.get("cost_cap_monthly_usd", 20.0)
        )
        self._query_timestamps: deque[float] = deque()

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

    def build_system_prompt(self, accounts: list[dict[str, Any]]) -> str:
        income = self._config.get("monthly_income", 0)
        goals = self._config.get("financial_goals", [])
        preferences = self._config.get("preferences", [])

        accounts_text = ""
        for acc in accounts:
            line = f"- {acc['name']} ({acc['institution']}, {acc.get('type', 'unknown')})"
            if acc.get("balance") is not None:
                line += f": ${acc['balance']:,.2f}"
            if acc.get("interest_rate"):
                line += f" @ {acc['interest_rate']*100:.1f}% APR"
            accounts_text += line + "\n"

        return f"""You are a personal financial advisor. You have access to the user's real financial data.

Monthly income: ${income:,.2f}
Financial goals: {', '.join(goals) if goals else 'Not set'}
Preferences: {', '.join(preferences) if preferences else 'None'}

Current accounts:
{accounts_text}

Rules:
- Be direct and actionable
- Reference specific numbers from the data
- Never suggest actions that move money (the system is read-only)
- If asked about something not in the data, say so"""

    async def query(
        self,
        user_message: str,
        accounts_summary: list[dict[str, Any]],
        force_tier: Tier | None = None,
    ) -> str:
        self._check_rate_limit()

        tier = force_tier or classify_tier(user_message)
        model = self.select_model(tier)
        system_prompt = self.build_system_prompt(accounts_summary)

        estimated_cost = _COST_PER_1K_TOKENS[tier] * 2
        self._cost_tracker.check_budget(estimated_cost)

        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
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

        return response.content[0].text

    @property
    def cost_tracker(self) -> CostTracker:
        return self._cost_tracker
